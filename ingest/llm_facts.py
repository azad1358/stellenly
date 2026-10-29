"""Facts an LLM read from a posting — German level, visa, relocation, salary — and checked against the text.

The LLM must quote the sentence each answer is based on. An answer is only kept if
that quote really appears in the posting (and, for salaries, if the number is
plausible). Kept answers are stored in data/cache/llm_facts.json, keyed by job id and
a hash of the description, so the ingester applies them on every run and a
changed posting gets checked again.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

FACTS_PATH = Path(__file__).parent.parent / "data" / "cache" / "llm_facts.json"
GERMAN_LEVELS = {"required", "nice_to_have", "not_required", "not_mentioned"}
_facts: dict | None = None


def text_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]


def load() -> dict:
    global _facts
    if _facts is None:
        _facts = json.loads(FACTS_PATH.read_text(encoding="utf-8")) if FACTS_PATH.exists() else {}
    return _facts


def save(facts: dict, keep: set[str] | None = None) -> None:
    if keep is not None:
        facts = {k: v for k, v in facts.items() if k in keep}
    FACTS_PATH.write_text(json.dumps(dict(sorted(facts.items())), ensure_ascii=False, separators=(",", ":"), indent=0) + "\n",
                          encoding="utf-8")


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9€]+", " ", (s or "").lower()).strip()


def quoted(quote: str, text: str) -> bool:
    """True if the quote (or its first 60 characters) appears in the text, ignoring case/punctuation."""
    q = _squash(quote)
    return len(q) >= 8 and (q in _squash(text) or q[:60] in _squash(text))


def verify(ans: dict, text: str, seniority: str) -> dict:
    """Turn an LLM answer into checked facts. Anything unproven is left out (the rules decide then)."""
    facts: dict = {"h": text_hash(text)}
    german = str(ans.get("german") or "").strip().lower()
    if german in GERMAN_LEVELS:
        if german == "not_mentioned":
            if "german" not in text.lower() and "deutsch" not in text.lower():
                facts["german"] = german
        elif quoted(str(ans.get("german_quote") or ""), text):
            facts["german"] = german
    if ans.get("salary_stated") is False:
        facts["salary"] = None  # the posting states no salary: never show one
    elif ans.get("salary_stated") is True and quoted(str(ans.get("salary_quote") or ""), text) \
            and re.search(r"\d", str(ans.get("salary_quote"))):
        try:
            lo = int(float(ans.get("salary_min_eur_year")))
            hi = int(float(ans.get("salary_max_eur_year") or lo))
        except (TypeError, ValueError):
            lo = hi = 0
        lo, hi = sorted((lo, hi))
        lo_cap, hi_cap = (60000, 75000) if seniority == "intern" else (300000, 450000)
        if 15000 <= lo <= lo_cap and hi <= hi_cap and hi <= lo * 3:
            facts["salary"] = [lo, hi]
    # "Offered" needs proof in the text; "not offered" is accepted (rules trip over e.g. "Visa card").
    for key, field, quote in (("visa", "visa_sponsorship", "visa_quote"), ("reloc", "relocation_support", "relocation_quote")):
        if ans.get(field) is True and quoted(str(ans.get(quote) or ""), text):
            facts[key] = True
        elif ans.get(field) is False:
            facts[key] = False
    return facts


def merge_into_current(ours_path: str) -> int:
    """Merge facts from another copy of llm_facts.json into the current one (that copy wins per job).
    Used when two runs saved the file at the same time. Returns how many jobs came from the other copy."""
    global _facts
    ours = json.loads(Path(ours_path).read_text(encoding="utf-8"))
    current = json.loads(FACTS_PATH.read_text(encoding="utf-8")) if FACTS_PATH.exists() else {}
    current.update(ours)
    _facts = current
    save(current)
    return len(ours)


def apply(row: dict, text: str) -> dict:
    """Overwrite rule-based fields with checked LLM facts for this job, if the posting hasn't changed."""
    f = load().get(row["id"])
    if not f or f.get("h") != text_hash(text):
        return row
    if "german" in f:
        row["german_level"] = f["german"]
    if "salary" in f:
        row["salary_min"], row["salary_max"] = (f["salary"] or (None, None))
    if "visa" in f:
        row["visa_sponsorship"] = f["visa"]
    if "reloc" in f:
        row["relocation"] = f["reloc"]
    return row


if __name__ == "__main__":  # python ingest/llm_facts.py --merge other.json
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--merge":
        print(f"merged {merge_into_current(sys.argv[2])} jobs into {FACTS_PATH.name}")
