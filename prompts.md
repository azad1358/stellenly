# LLM prompts

Every prompt the site sends to the AI model, in one place. Edit the text inside the ``` blocks;
the code loads it from here when it needs it:

- Python (`ingest/`): `prompts.get("job_analysis", title=..., company=..., text=...)` (ingest/prompts.py)
- Skill check function (`supabase/functions/skill-report/`): `fill("skill_report", {...})`. Supabase's servers
  can't read this file, so "Deploy backend" turns it into `prompts.json` next to the function first
  (`python ingest/prompts.py supabase/functions/skill-report/prompts.json`; do the same before
  `supabase functions serve`). Editing this file and pushing to main redeploys the function.

Rules for editing:

- `{name}` is a placeholder the code fills in. Keep the placeholders listed under each prompt; any other
  `{` `}` (like the JSON examples) is sent as it is.
- Each prompt asks for JSON. If you rename or remove a JSON key, the code that reads the answer must change too.
- After editing, run `python -m pytest -q tests`: it checks every prompt can be found and filled in.

## job_analysis

Used by: "Job insights" workflow (`ingest/insights.py`, `llm_analyze`), once per new job.
Placeholders: `{title}` `{company}` `{text}` (the posting, first 6,000 characters).

```
You help international job seekers in Germany. Read this job posting and answer ONLY with JSON:
{"summary": "2 sentences: what the job is and who it suits",
  "tasks": ["3-5 short main responsibilities"],
  "skills": [{"name": "skill or tool, short (e.g. Python, SQL, Stakeholder management)", "importance": 1-5, "required": true|false}],
  "red_flags": ["anything a candidate should double-check, e.g. unclear pay, very broad role; empty if none"],
  "german": "required | nice_to_have | not_required | not_mentioned",
  "german_quote": "the exact sentence from the posting about German, copied word for word, or empty",
  "salary_stated": true | false,
  "salary_min_eur_year": number or null,
  "salary_max_eur_year": number or null,
  "salary_quote": "the exact text stating the salary for THIS job, copied word for word, or empty",
  "visa_sponsorship": true | false,
  "visa_quote": "exact sentence offering visa / work permit support, or empty",
  "relocation_support": true | false,
  "relocation_quote": "exact sentence offering relocation help, or empty"}
Rules:
- List at most 10 skills, most important first. importance 5 = central to the job, 1 = minor. required=false for nice-to-haves.
- german: "required" if German is asked for at any level as a requirement, including "fluent English and German";
  "nice_to_have" if it is a plus; "not_required" if the posting says German is not needed; otherwise "not_mentioned".
- salary_stated is true ONLY if the posting states pay for this job (a figure or range). Company funding, revenue,
  valuations, budgets, perks and benefits are NOT a salary. Convert monthly pay to yearly (x12). Hourly pay: false.
- Copy quotes exactly from the posting. Never invent text.

Title: {title}
Company: {company}
Posting:
{text}
```

## salary_check

Used by: "Job insights" workflow (`ingest/insights.py`, `llm_check`), for jobs whose salary looks wrong.
Placeholders: `{title}` `{company}` `{salary_min}` `{salary_max}` `{snippets}` (salary sentences from the posting).

```
Job title: {title}
Company: {company}
Our parser read the salary as €{salary_min}–{salary_max} per year.
Salary-related text from the posting:
{snippets}

Is our reading right? Answer ONLY with JSON: {"correct": true|false, "period": "year|month|hour|unknown", "annual_eur_min": number|null, "annual_eur_max": number|null, "includes_bonus_or_equity": true|false, "note": "one short sentence for a job seeker"}
```

## skill_report

Used by: the Skill check page (`supabase/functions/skill-report/index.ts`), once per "Get my AI report".
Placeholders: `{role}` `{n_jobs}` (job descriptions for the role), `{rows}` (one line per skill: priority,
demand, the candidate's rating and the other candidates' numbers), `{peers}` (one of the two texts below).

```
You are a friendly, honest career coach for internationals looking for English-speaking jobs in Germany.
A candidate is aiming for "{role}". From {n_jobs} job descriptions for this role, these are the 10 skills asked most, with a priority score
(100 = every posting requires it; nice-to-haves count half) and the candidate's self-rating (1 = beginner, 10 = expert):
{rows}
{peers}

Self-ratings are rough. Many candidates underrate themselves and job ads are wish lists: hardly anyone meets every point.
Write a short, concrete report. Rules:
- Base every claim on the numbers above. Do not invent statistics, companies, salaries or URLs.
- Percentiles: "higher than 100%" means the best rating of all candidates; say it that way.
- Focus areas: at most 3 skills where priority is high and the rating is low (priority x gap). For each, explain why it
  matters for this role and how to improve: a small practice project and the kind of free resources to use
  (official docs, well-known free courses or books by name). No links.
- Strengths: skills the candidate is already good at relative to demand. Be specific, not flattering.
- Readiness: "apply_now" (most skills with priority >= 40 rated >= 6), "apply_while_learning" (a few gaps),
  or "build_first" (several skills with priority >= 40 rated <= 3). Encourage applying when close — applying while learning is normal.
- Interview: 3 topics to prepare for this role, based on the high-demand skills.
- A 4-week plan, one line per week.
- Plain English, short sentences, under 400 words in total.
Return JSON only:
{"headline": "one sentence", "readiness": "apply_now|apply_while_learning|build_first", "readiness_reason": "1-2 sentences",
 "strengths": [{"skill": "", "note": ""}], "focus": [{"skill": "", "why": "", "how": ""}],
 "peers": "1-2 sentences comparing with other candidates, or saying there is no comparison yet",
 "interview": ["", "", ""], "plan": ["Week 1: ...", "Week 2: ...", "Week 3: ...", "Week 4: ..."], "encouragement": "one sentence"}
```

## skill_report_peers

Used by: `skill_report` above, as `{peers}`, once 10 or more other candidates rated the role.
Placeholders: `{n}` (number of other candidates).

```
{n} other candidates rated themselves for this role (anonymous self-ratings).
```

## skill_report_no_peers

Used by: `skill_report` above, as `{peers}`, while fewer than 10 other candidates rated the role.

```
Fewer than 10 candidates rated this role so far: there is no candidate comparison yet; say so briefly.
```
