"""Rule-based enrichment: turns a raw job posting into clean, filterable fields.

Everything here is plain regex + small dictionaries so it is fast, free and
easy to tweak. Each function is unit-tested in test_enrich.py.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------------------
# Text cleanup
# ---------------------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_RE = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr)[^>]*>", re.I)
_WS_RE = re.compile(r"[ \t ]+")


def html_to_text(raw: str | None, max_len: int = 20000) -> str:
    """Strip HTML, keep line breaks between blocks, collapse whitespace."""
    if not raw:
        return ""
    text = _BLOCK_RE.sub("\n", raw)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:max_len]


def _norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"\(\s*[mwfdx]\s*/\s*[mwfdx]\s*/\s*[mwfdx]\s*\)", " ", s, flags=re.I)  # (m/w/d)
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return " ".join(s.split())


# ---------------------------------------------------------------------------
# Language: keep English postings only
# ---------------------------------------------------------------------------
_EN_HINTS = re.compile(r"\b(the|and|you|with|our|we|will|your|for|experience|team)\b", re.I)
_DE_HINTS = re.compile(r"\b(und|die|der|das|mit|wir|sie|für|ihre|unser|bei|eine?)\b", re.I)


def detect_language(text: str) -> str:
    """Return 'en', 'de' or 'other'. Uses langdetect when installed, falls back
    to a stop-word count (good enough for job ads)."""
    sample = (text or "")[:3000]
    if not sample.strip():
        return "other"
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0  # deterministic
        lang = detect(sample)
        return lang if lang in ("en", "de") else "other"
    except Exception:
        en = len(_EN_HINTS.findall(sample))
        de = len(_DE_HINTS.findall(sample))
        if en == 0 and de == 0:
            return "other"
        return "en" if en >= de else "de"


# ---------------------------------------------------------------------------
# German language requirement — the main differentiator
# ---------------------------------------------------------------------------
_GERMAN_NOT_REQUIRED = [
    r"\bno (prior )?german (language )?(skills |knowledge )?(is |are )?(required|needed|necessary)",
    r"\bgerman (language )?(skills |knowledge )?(is |are )?not (required|needed|necessary|a requirement|mandatory)",
    r"\b(don'?t|do not|doesn'?t|does not) (need|have) to speak german",
    r"\bwithout (any )?german",
    r"\bno need (for|to speak) german",
    r"\benglish only\b",
]
_GERMAN_NICE = [
    r"\bgerman[^.\n]{0,40}\b(is|are|would be|will be|as) (a |an )?(big |strong |real )?(plus|bonus|advantage|asset|nice[- ]to[- ]have|benefit|beneficial)",
    r"\bgerman[^.\n]{0,40}\bnice[- ]to[- ]have",
    r"\bgerman[^.\n]{0,30}\b(preferred|desirable|welcome|appreciated|optional)",
    r"\b(basic|some|conversational|beginner) (knowledge of |level of )?german",
    r"\bgerman (language )?(skills )?(at )?(level )?\(?(a1|a2|b1)\b",
    r"\bwillingness to learn german",
]
_GERMAN_REQUIRED = [
    r"\b(fluent|fluency|business[- ]fluent|native|very good|excellent|strong|proficient|proficiency|good command|full professional)\b[^.\n]{0,25}\bgerman",
    r"\bgerman\b[^.\n]{0,25}\b(fluent|fluency|native|mother tongue|c1|c2|b2)\b",
    r"\bgerman (language )?(skills |knowledge )?(is |are )?(required|mandatory|a must|essential|necessary|needed)",
    r"\b(must|need to|required to) (speak|be fluent in|have) [^.\n]{0,15}german",
    r"\bgerman and english\b[^.\n]{0,30}\b(required|fluent|mandatory|essential|written and spoken|both)",
    r"\b(both )?english and german\b[^.\n]{0,30}\b(required|fluent|mandatory|essential|written and spoken)",
    r"\b(fließend|verhandlungssicher|sehr gute?)\w*\s+deutsch",
    r"\bdeutschkenntnisse\b",
]
_C_NR = [re.compile(p, re.I) for p in _GERMAN_NOT_REQUIRED]
_C_NICE = [re.compile(p, re.I) for p in _GERMAN_NICE]
_C_REQ = [re.compile(p, re.I) for p in _GERMAN_REQUIRED]
_SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")


def german_level(text: str) -> str:
    """Classify what the posting says about German:
    'required' | 'nice_to_have' | 'not_required' | 'not_mentioned'.

    Works sentence by sentence so that "Fluent English required, German is a
    plus" is classified as nice_to_have, not required."""
    found = set()
    for sent in _SENT_SPLIT.split(text or ""):
        low = sent.lower()
        if "german" not in low and "deutsch" not in low:
            continue
        if any(p.search(sent) for p in _C_NR):
            found.add("not_required")
        elif any(p.search(sent) for p in _C_NICE):
            found.add("nice_to_have")
        elif any(p.search(sent) for p in _C_REQ):
            found.add("required")
    for level in ("required", "nice_to_have", "not_required"):
        if level in found:
            return level
    return "not_mentioned"


# ---------------------------------------------------------------------------
# Salary (yearly EUR, gross)
# ---------------------------------------------------------------------------
_NUM = r"(\d{1,3}(?:[.,\s]\d{3})?(?:[.,]\d{1,2})?\s?[kK]?)"
_CUR = r"(?:€|eur\b|euro\b|eur\.?)"
_RANGE_RE = re.compile(
    rf"(?:{_CUR}\s?)?{_NUM}\s?(?:{_CUR})?\s?(?:-|–|—|to|bis)\s?(?:{_CUR}\s?)?{_NUM}\s?(?:{_CUR})?",
    re.I,
)
_SINGLE_RE = re.compile(rf"(?:{_CUR}\s?{_NUM}|{_NUM}\s?{_CUR})", re.I)
_HOURLY_RE = re.compile(r"(per hour|/\s?h\b|/\s?hour|hourly|pro stunde|stundenlohn|€\s?/\s?std)", re.I)
_MONTHLY_RE = re.compile(r"(per month|/\s?month|monthly|monatlich|pro monat|brutto/monat)", re.I)


def _to_number(tok: str) -> float | None:
    tok = tok.strip().lower().replace(" ", "")
    k = tok.endswith("k")
    tok = tok.rstrip("k")
    # "65.000" / "65,000" → 65000 ; "65,5" → 65.5
    if re.fullmatch(r"\d{1,3}[.,]\d{3}", tok):
        tok = tok.replace(".", "").replace(",", "")
    else:
        tok = tok.replace(",", ".")
    try:
        val = float(tok)
    except ValueError:
        return None
    return val * 1000 if k else val


def _yearly(v: float, context: str) -> float:
    if v < 1000:  # "65k" already multiplied; bare "65" next to € likely thousands
        v = v * 1000
    if _MONTHLY_RE.search(context) and v < 15000:
        v = v * 12
    return v


def parse_salary(text: str) -> tuple[int | None, int | None]:
    """Find a yearly salary range in EUR. Ignores hourly pay. Returns (min, max)."""
    t = text or ""
    for m in _RANGE_RE.finditer(t):
        span = t[max(0, m.start() - 40): m.end() + 40]
        if not re.search(_CUR, span, re.I):
            continue  # require a currency nearby
        if _HOURLY_RE.search(span):
            continue
        a, b = _to_number(m.group(1)), _to_number(m.group(2))
        if a is None or b is None:
            continue
        a, b = _yearly(a, span), _yearly(b, span)
        lo, hi = sorted((a, b))
        if 15000 <= lo <= 400000 and hi <= 400000:
            return int(lo), int(hi)
    for m in _SINGLE_RE.finditer(t):
        span = t[max(0, m.start() - 40): m.end() + 40]
        if _HOURLY_RE.search(span):
            continue
        val = _to_number(m.group(1) or m.group(2))
        if val is None:
            continue
        val = _yearly(val, span)
        if 15000 <= val <= 400000:
            return int(val), int(val)
    return None, None


# ---------------------------------------------------------------------------
# Experience, seniority, remote, visa, relocation, agency
# ---------------------------------------------------------------------------
_YEARS_RE = re.compile(
    r"(\d{1,2})\s?\+?\s?(?:-|–|to)?\s?(?:\d{1,2})?\s?\+?\s?years?['’]?\s+(?:of\s+)?"
    r"(?:\w+\s+){0,3}?(?:experience|exp\b|working)",
    re.I,
)


def years_experience(text: str) -> int | None:
    vals = [int(m.group(1)) for m in _YEARS_RE.finditer(text or "")]
    vals = [v for v in vals if 0 < v <= 20]
    return min(vals) if vals else None


def seniority(title: str, years: int | None) -> str:
    t = (title or "").lower()
    if re.search(r"\b(intern|internship|praktik|werkstudent|working student|trainee|ausbildung|thesis)", t):
        return "intern"
    if re.search(r"\b(head of|principal|staff|lead|director|vp|chief|teamleit)", t):
        return "lead"
    if re.search(r"\b(senior|sr\.?)\b", t):
        return "senior"
    if re.search(r"\b(junior|jr\.?|entry|graduate|berufseinsteiger)\b", t):
        return "junior"
    if years is not None:
        if years <= 2:
            return "junior"
        if years <= 4:
            return "mid"
        return "senior"
    return "unspecified"


def remote_type(is_remote: bool | None, title: str, text: str) -> str:
    blob = f"{title}\n{text}".lower()
    if re.search(r"\bhybrid\b|\d\s?days? (a|per) week (in|at) (the )?office|teilweise remote", blob):
        return "hybrid"
    if is_remote or re.search(r"\b(fully remote|100\s?% remote|remote[- ]first|work from anywhere)\b", blob):
        if re.search(r"remote\s*\(?\s*(eu|europe|emea)|anywhere in (the )?(eu|europe)|across europe", blob):
            return "remote_eu"
        return "remote_de"
    if title and re.search(r"\bremote\b", title.lower()):
        return "remote_de"
    return "onsite"


_NO_VISA = re.compile(
    r"(no|not|unable to|cannot|can'?t|don'?t|do not|won'?t)\s+(offer\s+|provide\s+)?(visa\s+)?sponsor|"
    r"without (visa )?sponsorship|must (already )?have (a )?(valid )?(work|residence) permit|"
    r"(eu|german) (citizenship|work permit) (is )?required",
    re.I,
)
_VISA = re.compile(
    r"visa sponsorship|sponsor (your |a |the )?visa|visa (support|assistance|process)|"
    r"(help|support) (you )?with (your |the )?visa|blue card|relocation and visa|work permit support",
    re.I,
)
_RELOC = re.compile(
    r"relocation (package|support|assistance|budget|bonus|help|allowance)|"
    r"(support|help|assist)\w* (you )?(with )?(your )?relocat|umzugskosten|we (cover|pay) (your )?relocation",
    re.I,
)


def visa_sponsorship(text: str) -> bool:
    return bool(_VISA.search(text or "")) and not _NO_VISA.search(text or "")


def relocation(text: str) -> bool:
    return bool(_RELOC.search(text or ""))


_AGENCY_COMPANY = re.compile(
    r"personal(vermittlung|dienstleist|beratung|service)|recruit|staffing|headhunt|talent (partners|solutions)|"
    r"\b(hays|randstad|adecco|manpower|michael page|robert half|gulp|amadeus fire|orizon|"
    r"jobot|darwin recruitment|hirevue)\b|zeitarbeit|arbeitnehmerüberlassung|\bhr consulting\b",
    re.I,
)
_AGENCY_TEXT = re.compile(
    r"on behalf of (our|a) client|our client,? (is|a)|für unseren (kunden|mandanten)|"
    r"we are (currently )?recruiting for|i am (currently )?recruiting for|im auftrag unseres kunden",
    re.I,
)


def is_agency(company: str, text: str) -> bool:
    return bool(_AGENCY_COMPANY.search(company or "")) or bool(_AGENCY_TEXT.search(text or ""))


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------
# Cities and regions live in cities_de.json; keys below are _norm()-ed spellings.
_PLACES = json.loads((Path(__file__).parent / "cities_de.json").read_text(encoding="utf-8"))
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})


def _spellings(name: str) -> set[str]:
    return {_norm(name), _norm(name.translate(_UMLAUTS))}


_CITY_ALIASES = {"remote": "Remote"}
for _city, _aliases in _PLACES["cities"].items():
    for _name in [_city, *_aliases]:
        for _key in _spellings(_name):
            _CITY_ALIASES[_key] = _city
_REGIONS = {k for r in _PLACES["regions"] for k in _spellings(r)} | {"de"}

_DE_PLACE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in sorted(set(_CITY_ALIASES) - {"remote"} | _REGIONS - {"de"},
                                                     key=len, reverse=True)) + r")\b"
)
_DE_COUNTRY = re.compile(r"\b(?:germany|deutschland|allemagne|alemania|germania)\b")
_DE_CODE = re.compile(r"(?<![A-Za-z])DEU?(?![A-Za-z])")  # "Berlin, DE" (case-sensitive)
# Same-named towns abroad: Hanover NH, Berlin CT, Hamburg NY, Potsdam NY, Dresden ON ...
_ABROAD = re.compile(
    r"\b(?:USA|U\.S\.A?\.?|United States|Canada|Ontario)\b|,\s*(?:A[KLRZ]|C[AOT]|FL|GA|HI|I[ADLN]|K[SY]|LA|"
    r"M[ADEINOST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY]|ON|QC|BC)\b"
)


_FOREIGN = re.compile(
    r"\b(?:uk|u k|united kingdom|great britain|england|scotland|wales|northern ireland|ireland|france|netherlands|"
    r"the netherlands|holland|belgium|luxembourg|switzerland|austria|spain|portugal|italy|poland|czechia|"
    r"czech republic|slovakia|hungary|romania|bulgaria|greece|croatia|serbia|slovenia|sweden|denmark|norway|"
    r"finland|estonia|latvia|lithuania|ukraine|turkey|israel|cyprus|malta|usa|united states|canada|mexico|brazil|"
    r"india|singapore|australia|new zealand|japan|china|uae|dubai|"
    r"london|manchester|birmingham|edinburgh|glasgow|bristol|belfast|leeds|oxford|dublin|cork|paris|lyon|lille|"
    r"marseille|bordeaux|toulouse|nantes|amsterdam|rotterdam|the hague|den haag|utrecht|eindhoven|brussels|"
    r"antwerp|zurich|geneva|geneve|lausanne|basel|bern|zug|vienna|wien|graz|linz|salzburg|madrid|barcelona|"
    r"valencia|lisbon|porto|milan|rome|warsaw|krakow|wroclaw|prague|brno|budapest|bucharest|stockholm|"
    r"gothenburg|copenhagen|oslo|helsinki|tallinn|riga|vilnius|athens|new york|san francisco)\b"
)
_GENERIC_WORDS = {
    "remote", "hybrid", "office", "headquarter", "headquarters", "hq", "home", "homebased", "based", "emea", "europe",
    "european", "union", "eu", "anywhere", "worldwide", "global", "job", "jobs", "time", "zone", "timezone", "cet",
    "within", "or", "and", "in", "the", "flexible", "day", "days", "week", "a", "per", "first",
}


def abroad(location: str | None) -> bool:
    """Names a place outside Germany (and no German one): "Paris - full remote", "Remote, UK"."""
    return bool(_FOREIGN.search(_norm(location))) and not in_germany(location)


def generic_location(location: str | None) -> bool:
    """Only words like "Remote", "EMEA", "Hybrid", "Remote - Europe timezone": no actual place."""
    return all(w in _GENERIC_WORDS or w.isdigit() for w in _norm(location).split())


def in_germany(location: str | None) -> bool:
    """True if any part of a location string ("Berlin or London", "Munich; NYC") is in Germany."""
    for part in re.split(r"[;|]| / | or | & ", location or ""):
        norm = _norm(part)
        if _DE_COUNTRY.search(norm):
            return True
        if (_DE_PLACE.search(norm) or _DE_CODE.search(part)) and not _ABROAD.search(part):
            return True
    return False


_DE_CITY = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in sorted(set(_CITY_ALIASES) - {"remote"}, key=len, reverse=True)) + r")\b"
)
_LOC_NOISE = re.compile(r"\b(office|hq|headquarters?|hybrid|campus|building|onsite|on-site)\b", re.I)


def normalize_city(location: str | None) -> str | None:
    """First German city named in the location ("Munich - London" → Munich,
    "Berlin Office" → Berlin); otherwise the first part, cleaned up."""
    if not location:
        return None
    norm = _norm(location)
    if m := _DE_CITY.search(norm):
        return _CITY_ALIASES[m.group(0)]
    if re.search(r"\bremote\b", norm):
        return "Remote"
    for part in re.split(r"[,/|;(]| - | or | & ", location):  # a small town: "Geeste", "Parsdorf, Bavaria"
        part = _LOC_NOISE.sub(" ", part).strip(" -)")
        key = _norm(part)
        if key and key not in _REGIONS and not _DE_COUNTRY.search(key) and not _FOREIGN.search(key):
            return " ".join(part.split())[:60]
    return None


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
TAG_KEYWORDS = {
    "python": r"\bpython\b",
    "javascript": r"\bjavascript\b|\bnode\.?js\b",
    "typescript": r"\btypescript\b",
    "react": r"\breact(\.js)?\b",
    "java": r"\bjava\b(?!script)",
    "kotlin": r"\bkotlin\b",
    "go": r"\bgolang\b|\bgo developer\b",
    "php": r"\bphp\b|\blaravel\b",
    "dotnet": r"\.net\b|\bc#",
    "ai-ml": r"\bmachine learning\b|\b(ml|ai|llm|genai|nlp)\b|\bdeep learning\b|artificial intelligence",
    "data": r"\bdata (engineer|scien|analy)|\banalytics\b|\bsql\b",
    "devops": r"\bdevops\b|\bkubernetes\b|\bsre\b|\bplatform engineer|\bterraform\b",
    "cloud": r"\baws\b|\bazure\b|\bgcp\b|google cloud",
    "frontend": r"\bfront[- ]?end\b",
    "backend": r"\bback[- ]?end\b",
    "fullstack": r"\bfull[- ]?stack\b",
    "mobile": r"\b(ios|android|flutter|react native|mobile developer)\b",
    "qa": r"\bqa\b|\btest (engineer|automation)\b|\bquality assurance\b",
    "security": r"\bsecurity\b|\bcyber",
    "product": r"\bproduct (manager|owner)\b",
    "design": r"\b(ux|ui|product designer|graphic design)",
    "marketing": r"\bmarketing\b|\bseo\b|\bsocial media\b",
    "sales": r"\bsales\b|\baccount (executive|manager)\b|business development",
    "customer-support": r"customer (support|service|success)",
    "finance": r"\bfinance\b|\baccount(ing|ant)\b|\bcontrolling\b",
    "hr": r"\brecruiter\b|\bhuman resources\b|\btalent acquisition\b|\bhr\b",
    "operations": r"\boperations\b|\blogistics\b|\bsupply chain\b",
    "engineering": r"\bmechanical|\belectrical|\bembedded\b|\bhardware\b",
    "healthcare": r"\bnurse\b|\bmedical\b|\bclinical\b|\bpharma",
}
_TAG_RES = {tag: re.compile(rx, re.I) for tag, rx in TAG_KEYWORDS.items()}


def slug_tag(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _norm(t)).strip("-")[:40]


def make_tags(title: str, text: str, source_tags: list[str] | None, extra: dict) -> list[str]:
    tags: set[str] = set()
    head = f"{title}\n{(text or '')[:1500]}"
    for tag, rx in _TAG_RES.items():
        if rx.search(title or "") or (tag not in ("go", "java", "hr", "qa") and rx.search(head)):
            tags.add(tag)
    for t in source_tags or []:
        s = slug_tag(t)
        if s and len(s) <= 30:
            tags.add(s)
    if extra.get("seniority") not in (None, "unspecified"):
        tags.add(extra["seniority"])
    if extra.get("remote_type") in ("remote_de", "remote_eu"):
        tags.add("remote")
    if extra.get("visa_sponsorship"):
        tags.add("visa-sponsorship")
    if extra.get("relocation"):
        tags.add("relocation")
    if extra.get("german_level") in ("not_required",):
        tags.add("no-german")
    return sorted(tags)[:25]


# ---------------------------------------------------------------------------
# Dedupe key
# ---------------------------------------------------------------------------
def job_id(title: str, company: str, city: str | None) -> str:
    key = f"{_norm(title)}|{_norm(company)}|{_norm(city or '')}"
    return hashlib.sha1(key.encode()).hexdigest()[:20]


# ---------------------------------------------------------------------------
# One call to rule them all
# ---------------------------------------------------------------------------
def enrich(raw: dict) -> dict | None:
    """raw keys: source, source_id, url, title, company, location, description_html,
    is_remote, tags, job_types, posted_at (ISO string).
    Returns a row for ingest_jobs(), or None if the job should be skipped."""
    title = (raw.get("title") or "").strip()
    company = (raw.get("company") or "").strip()
    url = (raw.get("url") or "").strip()
    if not title or not company or not url:
        return None
    if re.search(r"\bTEST\b", title):  # ATS test postings ("TEST - Forward Deployed Engineer")
        return None

    text = html_to_text(raw.get("description_html"))
    if detect_language(f"{title}\n{text}") != "en":
        return None

    city = normalize_city(raw.get("location"))
    years = years_experience(text)
    row = {
        "id": job_id(title, company, city),
        "source": raw.get("source"),
        "source_id": str(raw.get("source_id") or "") or None,
        "url": url,
        "title": title[:300],
        "company": company[:200],
        "location": (raw.get("location") or "")[:200] or None,
        "city": city,
        "description": text,
        "job_types": [j for j in (raw.get("job_types") or []) if j][:10],
        "german_level": german_level(text),
        "visa_sponsorship": visa_sponsorship(text),
        "relocation": relocation(text),
        "years_experience": years,
        "seniority": seniority(title, years),
        "is_agency": is_agency(company, text),
        "remote_type": remote_type(raw.get("is_remote"), title, text),
        "posted_at": raw.get("posted_at"),
    }
    row["salary_min"], row["salary_max"] = parse_salary(text)
    row["tags"] = make_tags(title, text, raw.get("tags"), row)
    return row
