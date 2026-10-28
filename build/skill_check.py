"""The "Skill check" page: pick a role, rate the 10 skills its postings ask for most, get an AI report.

This module groups job titles into roles and writes web/skill-roles.json (role -> top skills), which both
the page and the Edge Function (supabase/functions/skill-report) read. Every job in the database counts,
also closed ones, so smaller roles have enough postings.

Priority score (0–100) of a skill for a role: 100 x share of postings asking for it x (0.5 + 0.5 x share of
those where it is a must-have) — a skill every posting requires scores 100, one every posting merely
"would like" scores 50.
"""
from __future__ import annotations

import re
from collections import Counter
from html import escape as e

MIN_JOBS = 15     # a role needs this many postings to be offered
TOP_SKILLS = 10

_CUT = re.compile(r"\s+[-–—|:/]\s+|[(,|]")
_GENDER = re.compile(r"\b[mwfdx]\s*/\s*[mwfdx](\s*/\s*[mwfdx])?\b|\ball genders\b", re.I)
_SENIORITY = re.compile(r"^(senior|sr\.?|junior|jr\.?|principal|lead|staff|mid[- ]level|associate|intern|working student|"
                        r"werkstudent)\s+", re.I)
NOT_A_ROLE = {"working student", "werkstudent", "intern", "internship", "trainee", "team lead", "senior manager",
              "manager", "lead", "student"}  # a level or a contract type, not a job


def _words(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9+#]+", s.lower()))


def role_name(title: str) -> str:
    """'Senior Data Scientist (m/w/d) – NLP' -> 'Data Scientist'."""
    t = _CUT.split(_GENDER.sub(" ", title), maxsplit=1)[0].strip()
    while (m := _SENIORITY.match(t)) and len(t[m.end():].split()) >= 2:
        t = t[m.end():].strip()
    return re.sub(r"\s+", " ", t)


def priority(share: float, must: float) -> int:
    return round(100 * share * (0.5 + 0.5 * must))


def roles(rows: list[dict]) -> list[dict]:
    """rows: [{"title", "skills": [{"n", "r"}, ...]}] -> roles with their most-asked skills, biggest first."""
    names: dict[str, Counter] = {}
    for r in rows:
        name = role_name(r["title"])
        key = _words(name)
        if 2 <= len(key.split()) <= 5 and key not in NOT_A_ROLE:
            names.setdefault(key, Counter())[name] += 1
    titles = [f" {_words(r['title'])} " for r in rows]
    out = []
    for key, forms in names.items():
        if sum(forms.values()) < 3:
            continue
        hits = [r for r, t in zip(rows, titles) if f" {key} " in t]  # "Data Scientist" also matches "Senior Data Scientist, NLP"
        if len(hits) < MIN_JOBS:
            continue
        asked, required = Counter(), Counter()
        for r in hits:
            for s in {s["n"]: s for s in r["skills"]}.values():
                asked[s["n"]] += 1
                required[s["n"]] += int(bool(s.get("r", 1)))
        skills = [{"n": s, "s": round(c / len(hits), 2), "r": round(required[s] / c, 2),
                   "p": priority(c / len(hits), required[s] / c)} for s, c in asked.most_common(TOP_SKILLS)]
        out.append({"t": forms.most_common(1)[0][0], "n": len(hits), "skills": sorted(skills, key=lambda x: -x["p"])})
    return sorted(out, key=lambda x: -x["n"])


def body(roles_: list[dict], n_jobs: int) -> str:
    return f"""<nav class="crumbs"><a href="index.html">Stellenly</a> › Skill check</nav>
<h1>Skill check: am I ready for this role?</h1>
<p class="lead">Pick the role you are aiming for. We show the 10 skills its postings ask for most — out of
{n_jobs:,} job descriptions — each with a priority score. Rate yourself from 1 to 10 and get an AI report: where you
already stand, what to learn first, and how you compare with other candidates.</p>
<form id="sc-role-form" class="sc-card" autocomplete="off">
  <label for="sc-role">Role</label>
  <div class="sc-row">
    <input id="sc-role" list="sc-roles" placeholder="e.g. {e(roles_[0]['t']) if roles_ else 'Data Scientist'}" required>
    <datalist id="sc-roles">{''.join(f'<option value="{e(r["t"])}">' for r in roles_)}</datalist>
    <button class="btn primary" type="submit">Show skills</button>
  </div>
  <p class="sc-hint" id="sc-role-hint">{len(roles_)} roles with at least {MIN_JOBS} postings.</p>
</form>
<form id="sc-skills" class="sc-card" hidden></form>
<section id="sc-report" class="sc-card sc-report" hidden aria-live="polite"></section>
<p class="sc-privacy">Anonymous: your ratings are saved in this browser for your next check, and stored without
your name, email or IP address (only the role and the numbers) to compare candidates.
<a href="privacy.html#skill-check">Privacy</a></p>"""
