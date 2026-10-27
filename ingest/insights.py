"""Daily job-quality pass: embeddings -> similar jobs -> peer statistics -> hints.

For every active job:
  1. embed title + description (small open model, cached between runs),
  2. find the most similar jobs at other companies ("peers"),
  3. compare salary, German requirement, visa and experience with the peers,
  4. turn rules + comparisons into short hints for the job card,
  5. optionally ask an LLM to double-check salaries that look like data errors.
Results go to jobs.insights via set_job_insights().

    python ingest/insights.py              # needs SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
    python ingest/insights.py --dry-run    # read-only (anon key is enough), prints a summary

Optional LLM check (any OpenAI-compatible API, e.g. Groq's free tier):
    LLM_API_KEY=...  [LLM_API_URL=https://api.groq.com/openai/v1/chat/completions]  [LLM_MODEL=llama-3.1-8b-instant]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).parent))
from skills import canonical_skill, extract_skills  # noqa: E402

CACHE = Path(__file__).parent / ".cache"
MODEL = "BAAI/bge-small-en-v1.5"
EMBED_VERSION = 2     # bump when the text that gets embedded changes (rebuilds the cache)
SKILLS_VERSION = 2    # bump when skills.py changes (re-extracts skills for all jobs)
TITLE_WEIGHT = 0.6    # job = 0.6 * title + 0.4 * description, so the role matters more than boilerplate
PEERS = 30            # similar jobs used for German / visa / experience stats
SALARY_PEERS = 15     # similar jobs *with a salary* used for salary stats
MIN_SALARY_PEERS = 8  # fewer than this: "not enough data to compare"
MIN_SIM = 0.75        # cosine similarity below this is not a "similar job" (tuned on live data)
MIN_SALARY_SIM = 0.72 # a bit looser for salary peers: only ~15% of jobs list a salary
BATCH = 500


# ---------------------------------------------------------------- Supabase
def _env(name: str) -> str:
    return os.environ[name].rstrip("/") if name == "SUPABASE_URL" else os.environ[name]


def _key() -> str:
    return os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_ANON_KEY"]


def rest(path: str, params: dict, headers: dict | None = None) -> list[dict]:
    key = _key()
    r = requests.get(f"{_env('SUPABASE_URL')}/rest/v1/{path}", params=params, timeout=60,
                     headers={"apikey": key, "Authorization": f"Bearer {key}", **(headers or {})})
    r.raise_for_status()
    return r.json()


def rpc(name: str, body: dict) -> str:
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    r = requests.post(f"{_env('SUPABASE_URL')}/rest/v1/rpc/{name}", data=json.dumps(body), timeout=120,
                      headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    if r.status_code >= 300:
        raise RuntimeError(f"{name} failed: {r.status_code} {r.text[:300]}")
    return r.text


COLS = ("id,title,company,city,seniority,salary_min,salary_max,years_experience,german_level,"
        "visa_sponsorship,is_agency,repost_count")


def fetch_active() -> list[dict]:
    out, start = [], 0
    while True:
        batch = rest("jobs", {"select": COLS, "is_active": "eq.true", "order": "id"},
                     {"Range": f"{start}-{start + 999}"})
        out += batch
        if len(batch) < 1000:
            return out
        start += 1000


def fetch_texts(ids: list[str]) -> dict[str, str]:
    out = {}
    for i in range(0, len(ids), 80):
        chunk = ids[i:i + 80]
        quoted = ",".join('"' + x.replace('"', "") + '"' for x in chunk)
        for r in rest("jobs", {"select": "id,description", "id": f"in.({quoted})"}):
            out[r["id"]] = r.get("description") or ""
    return out


# ---------------------------------------------------------------- embeddings (cached)
def load_cache() -> tuple[dict[str, np.ndarray], dict]:
    vecs, meta = {}, {}
    if (CACHE / f"embeddings-v{EMBED_VERSION}.npz").exists():
        z = np.load(CACHE / f"embeddings-v{EMBED_VERSION}.npz", allow_pickle=False)
        vecs = dict(zip(z["ids"].tolist(), z["vecs"]))
    if (CACHE / "meta.json").exists():
        meta = json.loads((CACHE / "meta.json").read_text(encoding="utf-8"))
    return vecs, meta


def save_cache(vecs: dict[str, np.ndarray], meta: dict, keep: set[str]) -> None:
    CACHE.mkdir(exist_ok=True)
    ids = [i for i in vecs if i in keep]
    np.savez_compressed(CACHE / f"embeddings-v{EMBED_VERSION}.npz", ids=np.array(ids),
                        vecs=np.stack([vecs[i] for i in ids]).astype(np.float16) if ids else np.zeros((0, 384)))
    meta = {i: m for i, m in meta.items() if i in keep}
    (CACHE / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


# Must address the applicant ("send your CV via WhatsApp", "contact us on Telegram"); product
# descriptions and anti-scam notices ("we will never contact you via WhatsApp") don't count.
_CONTACT = (r"\b(apply|send (your|us|me)|submit your|contact (us|me)|message (us|me)|reach (us|me)|"
            r"text (us|me)|write (to )?(us|me))\b[^.\n]{0,40}")
_NEGATION = re.compile(r"\b(never|not|don't|do not|won't|will not|no one|nobody)\b", re.I)
_SCAM = [
    (_CONTACT + r"\bwhats\s?app\b", "asks you to apply via WhatsApp"),
    (_CONTACT + r"\btelegram\b", "asks you to apply via Telegram"),
    (r"[\w.+-]+@(gmail|yahoo|hotmail|outlook|gmx|web)\.(com|de)\b", "uses a free email address instead of a company one"),
    (r"\b(registration|training|starter|application|onboarding)\s+(fee|deposit)\b|\byou (will )?(need to|must) pay\b",
     "asks applicants to pay a fee or deposit"),
    (r"\b(crypto|forex)\s+(trading|signals)\b", "is about crypto/forex trading"),
    (r"\bno experience (needed|required)\b.{0,80}(€|eur)\s?\d", "promises high pay with no experience"),
]


def scam_signals(text: str) -> list[str]:
    out = []
    for pat, label in _SCAM:
        for m in re.finditer(pat, text, re.I):
            line_start = max(text.rfind("\n", 0, m.start()), text.rfind(".", 0, m.start())) + 1
            context = text[max(0, line_start - 60):m.start()]  # this sentence + the heading before it
            if not _NEGATION.search(context + m.group(0)):
                out.append(label)
                break
    return out


def embed_missing(jobs: list[dict], vecs: dict, meta: dict) -> int:
    """Embed new jobs, and (re)extract text features — scam signals, skills — where they are missing or outdated."""
    missing = {j["id"] for j in jobs if j["id"] not in vecs}
    todo = [j["id"] for j in jobs if j["id"] in missing or meta.get(j["id"], {}).get("sv") != SKILLS_VERSION]
    if not todo:
        return 0
    model = None
    if missing:
        from fastembed import TextEmbedding  # imported lazily: heavy
        model = TextEmbedding(MODEL, cache_dir=str(CACHE / "models"))
    by_id = {j["id"]: j for j in jobs}
    for i in range(0, len(todo), 256):
        chunk = todo[i:i + 256]
        texts = fetch_texts(chunk)
        new = [x for x in chunk if x in missing]
        if new:
            titles = list(model.embed([by_id[x]["title"] for x in new], batch_size=64))
            bodies = list(model.embed([texts.get(x, "")[:1500] or by_id[x]["title"] for x in new], batch_size=64))
            for x, t, b in zip(new, titles, bodies):
                v = TITLE_WEIGHT * t / np.linalg.norm(t) + (1 - TITLE_WEIGHT) * b / np.linalg.norm(b)
                vecs[x] = (v / np.linalg.norm(v)).astype(np.float16)
        for x in chunk:
            m = meta.setdefault(x, {})
            m["scam"] = scam_signals(texts.get(x, ""))
            m["skills"] = extract_skills(by_id[x]["title"], texts.get(x, ""), company=by_id[x]["company"])
            m["sv"] = SKILLS_VERSION
        print(f"  processed {min(i + 256, len(todo))}/{len(todo)} ({len(new)} embedded)")
    return len(missing)


# ---------------------------------------------------------------- optional LLM job analysis
def _llm(prompt: str) -> dict | None:
    """One JSON answer from an OpenAI-compatible chat API. None if unavailable or rate-limited."""
    key = os.environ.get("LLM_API_KEY")
    if not key:
        return None
    r = requests.post(os.environ.get("LLM_API_URL", "https://api.groq.com/openai/v1/chat/completions"), timeout=90,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": os.environ.get("LLM_MODEL", "llama-3.1-8b-instant"), "temperature": 0,
                            "response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": prompt}]})
    if r.status_code == 429:
        raise RuntimeError("rate limit")
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


ANALYSIS_PROMPT = """You help international job seekers in Germany. Read this job posting and answer ONLY with JSON:
{{"summary": "2 sentences: what the job is and who it suits",
  "tasks": ["3-5 short main responsibilities"],
  "skills": [{{"name": "skill or tool, short (e.g. Python, SQL, Stakeholder management)", "importance": 1-5, "required": true|false}}],
  "red_flags": ["anything a candidate should double-check, e.g. unclear pay, very broad role; empty if none"]}}
List at most 10 skills, most important first. importance 5 = central to the job, 1 = minor. required=false for nice-to-haves.

Title: {title}
Company: {company}
Posting:
{text}"""


def llm_analyze(jobs: list[dict], meta: dict) -> int:
    """Summary, tasks and ranked skills per job, read by an LLM. Cached: each job is analysed once."""
    if not os.environ.get("LLM_API_KEY"):
        return 0
    todo = [j for j in jobs if "ai" not in meta.get(j["id"], {})][:int(os.environ.get("LLM_MAX_JOBS", 150))]
    texts = fetch_texts([j["id"] for j in todo]) if todo else {}
    done = 0
    for j in todo:
        try:
            ans = _llm(ANALYSIS_PROMPT.format(title=j["title"], company=j["company"], text=texts.get(j["id"], "")[:6000]))
        except RuntimeError:
            print("  LLM rate limit reached; the rest waits for the next run")
            break
        except Exception as e:
            print(f"  ! LLM analysis failed for {j['id']}: {e}")
            continue
        if not ans:
            break
        skills = []
        for s in ans.get("skills") or []:
            name = str(s.get("name") or "").strip()[:40]
            if name:
                imp = min(5, max(1, int(s.get("importance") or 3)))
                skills.append({"n": canonical_skill(name), "w": round(imp / 5, 2), "r": int(bool(s.get("required", True)))})
        meta.setdefault(j["id"], {})["ai"] = {
            "summary": str(ans.get("summary") or "")[:400],
            "tasks": [str(t)[:140] for t in (ans.get("tasks") or [])][:5],
            "flags": [str(t)[:160] for t in (ans.get("red_flags") or [])][:3],
            "skills": sorted(skills, key=lambda s: -s["w"])[:10],
        }
        done += 1
        time.sleep(2.1)  # free tiers allow ~30 requests per minute
    return done


# ---------------------------------------------------------------- peers + hints
def mid_salary(j: dict) -> float | None:
    if not j.get("salary_min"):
        return None
    return (j["salary_min"] + (j.get("salary_max") or j["salary_min"])) / 2


def eur(n: float) -> str:
    return f"€{round(n / 1000)}k"


SENIORITY_GROUP = {"intern": "entry", "junior": "entry", "mid": "mid", "senior": "senior", "lead": "senior"}
STUDENT_TITLE = re.compile(r"\b(intern|internship|praktikum|praktikant|werkstudent|working student|trainee|"
                           r"ausbildung|apprentice|thesis|abschlussarbeit)\b", re.I)


def norm_title(t: str) -> str:
    t = re.sub(r"\((?:[mwfdx]\s*/\s*){1,3}[mwfdx]\)|\(all genders\)", " ", t.lower())
    return " ".join(re.findall(r"[a-z0-9]+", t))


def compute(jobs: list[dict], vecs: dict, meta: dict) -> dict[str, dict]:
    n = len(jobs)
    E = np.stack([vecs[j["id"]].astype(np.float32) for j in jobs])
    company = np.array([j["company"].strip().lower() for j in jobs])
    group = np.array([SENIORITY_GROUP.get(j["seniority"], "") for j in jobs])
    sal = np.array([mid_salary(j) or np.nan for j in jobs])
    implausible = np.array([(j["seniority"] == "intern" and (j["salary_min"] or 0) > 60000) or (j["salary_min"] or 0) > 300000
                            for j in jobs])
    sal[implausible] = np.nan  # parsing mistakes in old rows must not skew the comparisons
    has_sal = ~np.isnan(sal)
    german_req = np.array([j["german_level"] == "required" for j in jobs])
    no_german = np.array([j["german_level"] in ("not_required", "nice_to_have") for j in jobs])
    visa = np.array([bool(j["visa_sponsorship"]) for j in jobs])
    years = np.array([j["years_experience"] if j["years_experience"] is not None else np.nan for j in jobs], float)

    # Skills per job: the LLM's reading when available, otherwise the rule-based extraction.
    job_skills = [(meta.get(j["id"], {}).get("ai") or {}).get("skills") or meta.get(j["id"], {}).get("skills") or []
                  for j in jobs]
    skill_sets = [{s["n"] for s in sk} for sk in job_skills]

    # Same role posted in many cities (talent pools, agencies).
    spread = collections.defaultdict(set)
    for j in jobs:
        spread[(j["company"].lower(), norm_title(j["title"]))].add(j.get("city") or "")

    out = {}
    for start in range(0, n, 512):
        S = E[start:start + 512] @ E.T  # cosine similarity (vectors are normalised)
        for r in range(S.shape[0]):
            i = start + r
            j = jobs[i]
            s = S[r].copy()
            s[company == company[i]] = -1  # peers = other companies (and never itself)

            k = min(PEERS, n - 1)
            top = np.argpartition(-s, k)[:k] if k > 0 else np.array([], int)
            top = top[s[top] >= MIN_SIM]
            top = top[np.argsort(-s[top])]

            # Salary peers: similar jobs that list a salary, same seniority group if there are enough.
            cand = np.where(has_sal & (s >= MIN_SALARY_SIM))[0]
            if group[i] and (group[cand] == group[i]).sum() >= MIN_SALARY_PEERS:
                cand = cand[group[cand] == group[i]]
            cand = cand[np.argsort(-s[cand])][:SALARY_PEERS]

            peers = {"n": int(len(top))}
            if len(top):
                peers.update({"german_req": round(float(german_req[top].mean()), 2),
                              "no_german": round(float(no_german[top].mean()), 2),
                              "visa": round(float(visa[top].mean()), 2)})
                y = years[top][~np.isnan(years[top])]
                if len(y) >= 5:
                    peers["years"] = float(np.median(y))
            if len(cand) >= MIN_SALARY_PEERS:
                q = np.percentile(sal[cand], [25, 50, 75])
                peers["salary"] = {"n": int(len(cand)), "p25": int(q[0]), "p50": int(q[1]), "p75": int(q[2])}

            hints = make_hints(j, peers, sal[i], meta.get(j["id"], {}),
                               len(spread[(j["company"].lower(), norm_title(j["title"]))]))
            entry = {"peers": peers, "hints": hints, "similar": [jobs[k]["id"] for k in top[:8]]}

            # Skills, with how often similar jobs ask for the same skill ("p"), and skills
            # that similar jobs commonly ask for but this posting doesn't mention.
            if job_skills[i]:
                share = (lambda name: round(sum(name in skill_sets[k] for k in top) / len(top), 2)) if len(top) >= 5 \
                    else (lambda name: None)
                entry["skills"] = [{**s, "p": share(s["n"])} for s in job_skills[i]]
            if len(top) >= 5:
                counts = collections.Counter(name for k in top for name in skill_sets[k])
                entry["peer_skills"] = [{"n": name, "p": round(c / len(top), 2)} for name, c in counts.most_common(12)
                                        if name not in skill_sets[i] and c / len(top) >= 0.3][:5]
            ai = meta.get(j["id"], {}).get("ai")
            if ai:
                entry["ai"] = {k: ai[k] for k in ("summary", "tasks", "flags") if ai.get(k)}
            out[j["id"]] = entry
    return out


def make_hints(j: dict, peers: dict, salary: float, meta: dict, n_cities: int) -> list[dict]:
    """[{"l": warn|good|info, "s": short badge text, "t": full sentence, "k": code}]"""
    hints = []

    def add(level, code, short, text):
        hints.append({"l": level, "k": code, "s": short, "t": text})

    ps = peers.get("salary")
    student = j["seniority"] == "intern" or bool(STUDENT_TITLE.search(j["title"]))
    if not np.isnan(salary):
        rng = f"similar jobs pay {eur(ps['p25'])}–{eur(ps['p75'])}" if ps else None
        if student and salary > 70000:
            add("warn", "salary_error", "⚠ Check salary",
                f"{eur(salary)} is far above what internships and student jobs pay"
                f"{' (' + rng + ')' if rng else ''}. The figure is probably a parsing error or not a yearly salary.")
        elif j["seniority"] == "junior" and salary > 120000:
            add("warn", "salary_error", "⚠ Check salary",
                f"{eur(salary)} is very high for a junior role{' (' + rng + ')' if rng else ''}. Check the original posting.")
        elif ps and salary > ps["p50"] * 1.8:
            add("warn", "salary_high", "⚠ Unusually high pay",
                f"{eur(salary)} is far above similar jobs ({eur(ps['p25'])}–{eur(ps['p75'])}, median {eur(ps['p50'])}). "
                "It may include bonus or equity, or be a data error.")
        elif ps and salary < ps["p50"] * 0.55:
            add("warn", "salary_low", "⚠ Unusually low pay",
                f"{eur(salary)} is far below similar jobs (median {eur(ps['p50'])}). It may be part-time or monthly.")
        elif ps and salary >= ps["p75"]:
            add("good", "salary_top", "💶 Top 25% pay",
                f"Pays more than 75% of {ps['n']} similar jobs (median {eur(ps['p50'])}).")
        elif ps and salary <= ps["p25"]:
            add("info", "salary_bottom", "Below-average pay",
                f"Pays less than 75% of {ps['n']} similar jobs (median {eur(ps['p50'])}).")
        if j.get("salary_max") and j["salary_max"] > 2.5 * j["salary_min"]:
            add("info", "salary_wide", "Very wide range",
                f"The range {eur(j['salary_min'])}–{eur(j['salary_max'])} is very wide; the real offer may be at the low end.")

    yrs = j.get("years_experience")
    if yrs and (student or j["seniority"] == "junior") and yrs >= 5:
        add("warn", "experience_mismatch", "⚠ Experience vs level",
            f"Labelled as {'a student/intern' if student else 'junior'} role but asks for {yrs}+ years of experience.")
    elif yrs and peers.get("years") is not None and yrs >= peers["years"] + 4:
        add("info", "experience_high", "Asks more experience",
            f"Asks for {yrs}+ years; similar jobs usually ask for about {peers['years']:g}.")

    if peers.get("n", 0) >= 10:
        if j["german_level"] in ("not_required", "nice_to_have") and peers["german_req"] >= 0.5:
            add("good", "german_rare", "🇬🇧 Rare: no German",
                f"{round(peers['german_req'] * 100)}% of similar jobs require German — this one doesn't.")
        if j["visa_sponsorship"] and peers["visa"] < 0.1 and peers["n"] >= 15:
            add("good", "visa_rare", "🛂 Rare: visa support",
                f"Only {round(peers['visa'] * 100)}% of similar jobs mention visa sponsorship.")

    if n_cities >= 5:
        add("info", "many_cities", f"Posted in {n_cities} cities",
            f"The same role is listed in {n_cities} cities — often a talent pool or an agency rather than one open position.")
    for label in meta.get("scam", []):
        add("warn", "scam_signal", "⚠ Be careful", f"This posting {label}. Legitimate employers rarely do that.")

    llm = meta.get("llm")
    if llm and llm.get("note") and any(h["k"] in ("salary_error", "salary_high", "salary_low") for h in hints):
        add("info", "salary_check", "Salary checked", llm["note"])
    return hints


# ---------------------------------------------------------------- optional LLM salary check
def llm_check(jobs: list[dict], insights: dict, meta: dict, limit: int = 40) -> int:
    key = os.environ.get("LLM_API_KEY")
    if not key:
        return 0
    url = os.environ.get("LLM_API_URL", "https://api.groq.com/openai/v1/chat/completions")
    model = os.environ.get("LLM_MODEL", "llama-3.1-8b-instant")
    todo = [j for j in jobs
            if any(h["k"] in ("salary_error", "salary_high", "salary_low") for h in insights[j["id"]]["hints"])
            and meta.get(j["id"], {}).get("llm", {}).get("for") != [j["salary_min"], j["salary_max"]]][:limit]
    texts = fetch_texts([j["id"] for j in todo]) if todo else {}
    done = 0
    for j in todo:
        text = texts.get(j["id"], "")
        snippets = " … ".join(m.group(0) for m in re.finditer(
            r"[^.\n]{0,160}(€|eur\b|euro|salary|gehalt|compensation|k\b|ote)[^.\n]{0,160}", text, re.I))[:1500]
        prompt = (
            f"Job title: {j['title']}\nCompany: {j['company']}\n"
            f"Our parser read the salary as €{j['salary_min']}–{j.get('salary_max') or j['salary_min']} per year.\n"
            f"Salary-related text from the posting:\n{snippets or '(none found)'}\n\n"
            "Is our reading right? Answer ONLY with JSON: "
            '{"correct": true|false, "period": "year|month|hour|unknown", "annual_eur_min": number|null, '
            '"annual_eur_max": number|null, "includes_bonus_or_equity": true|false, '
            '"note": "one short sentence for a job seeker"}')
        try:
            r = requests.post(url, timeout=60, headers={"Authorization": f"Bearer {key}"}, json={
                "model": model, "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}]})
            if r.status_code == 429:
                print("  LLM rate limit reached; the rest waits for the next run")
                break
            r.raise_for_status()
            ans = json.loads(r.json()["choices"][0]["message"]["content"])
        except Exception as e:
            print(f"  ! LLM check failed for {j['id']}: {e}")
            continue
        meta.setdefault(j["id"], {})["llm"] = {"for": [j["salary_min"], j["salary_max"]],
                                               "note": str(ans.get("note") or "")[:240], "answer": ans}
        done += 1
        time.sleep(2)  # stay well inside free-tier rate limits
    return done


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="don't write to Supabase; print a summary")
    args = ap.parse_args()

    jobs = fetch_active()
    vecs, meta = load_cache()
    new = embed_missing(jobs, vecs, meta)
    jobs = [j for j in jobs if j["id"] in vecs]
    analysed = llm_analyze(jobs, meta)
    insights = compute(jobs, vecs, meta)
    if llm_check(jobs, insights, meta):
        insights = compute(jobs, vecs, meta)  # fold the LLM notes into the hints
    save_cache(vecs, meta, {j["id"] for j in jobs})
    if analysed:
        print(f"LLM analysed {analysed} jobs")

    counts = collections.Counter(h["k"] for v in insights.values() for h in v["hints"])
    with_salary_stats = sum("salary" in v["peers"] for v in insights.values())
    print(f"{len(jobs)} jobs, {new} newly embedded, {with_salary_stats} with salary comparison")
    print("Hints:", dict(counts.most_common()))

    if args.dry_run:
        out = CACHE / "insights_preview.json"
        out.write_text(json.dumps(insights, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Preview written to {out}")
        return
    rows = [{"id": i, "insights": v} for i, v in insights.items()]
    written = 0
    for i in range(0, len(rows), BATCH):
        written += int(rpc("set_job_insights", {"payload": rows[i:i + BATCH]}) or 0)
    print(f"Wrote insights for {written} jobs")


if __name__ == "__main__":
    sys.exit(main())
