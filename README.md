# English Jobs Germany

A free, no-account job search for English-speaking jobs in Germany.
It shows the **German requirement, salary, EU Blue Card eligibility, visa
sponsorship and remote setup up front**, and hides dead and agency postings.

- **Frontend:** plain HTML + CSS + vanilla JS (`web/`), no build step
- **Database:** Supabase free tier (Postgres full-text search)
- **Updates:** GitHub Actions cron, Python ingester (`ingest/`)
- **Hosting:** Cloudflare Pages or GitHub Pages (free)
- **Money:** a Ko-fi link. No payments, cards or user profiles on your side.

```
GitHub Actions (every 6h) ── fetch APIs ─► enrich (English? German level? salary…) ─► Supabase
GitHub Actions (daily)    ── re-open original postings ─► hide dead ones
Browser ── search_jobs() RPC with the public anon key (read-only) ◄─ static site
```

## Try it now (no setup)

Open `web/index.html` in a browser. With an empty `SUPABASE_URL` the site
runs on built-in demo jobs, so you can click through every feature.

## Go live in ~30 minutes

1. **Supabase.** Create a free project (region: Frankfurt), then apply the schema
   with `npx supabase link --project-ref <ref>` and `npx supabase db push`
   (see [Database changes](#database-changes)).
2. **Keys.** In Project Settings → API, copy the Project URL, the anon/publishable key
   and the service_role key.
3. **GitHub.** Push this folder to a repo. Under Settings → Secrets → Actions, add:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY` (secret; never put it in `web/`)
4. **First import.** Actions → *Ingest jobs* → *Run workflow*. Check the log
   for the stats line (how many English jobs, German levels, salaries).
5. **Frontend.** Edit `web/config.js`: Supabase URL, anon key, Ko-fi link, costs.
6. **Deploy.** Cloudflare Pages → connect the repo → build command *none*, output
   directory `web`. Point your domain at it.
7. **RSS (optional).** `supabase functions deploy rss --no-verify-jwt`, then
   `supabase secrets set SITE_URL=https://your-domain SITE_NAME="English Jobs Germany"`.
8. **Legal.** Fill in `web/impressum.html` and `web/privacy.html` (templates).

Run locally:

```bash
pip install -r ingest/requirements.txt
python -m pytest -q ingest                       # enrichment rules
python ingest/ingest.py --dry-run --max-pages 2  # see what would be imported
```

## Database changes

The schema is versioned with Supabase CLI migrations, which work like Alembic.
Each change is a timestamped SQL file in `supabase/migrations/`. The database
records which files it has already run (`supabase_migrations.schema_migrations`),
so `db push` only runs new ones and never recreates tables or wipes data.

```bash
npx supabase migration new add_job_language   # creates supabase/migrations/<timestamp>_add_job_language.sql
# write the SQL change in that file, then:
npx supabase migration list                   # local vs. production: what is pending
npx supabase db push --dry-run                # preview
npx supabase db push                          # apply to production
```

Pushing a new migration to `main` also applies it automatically
(**Actions → Migrate database**). That workflow needs these secrets:
`SUPABASE_ACCESS_TOKEN` (account → Access Tokens), `SUPABASE_DB_PASSWORD`, and
`SUPABASE_PROJECT_ID` (the ref in your project URL).

Rules that keep production data safe:

- Never edit a migration that has already been applied. Add a new one instead.
- Add columns as nullable or with a `default` (`alter table public.jobs add column if not exists lang text default 'en';`).
- Rename with `alter table … rename column`. Dropping and re-adding a column deletes its data.
- Avoid `drop table`, `truncate` and `drop column` unless you mean to delete that data.
  For risky changes, take a backup first (Dashboard → Database → Backups, or `npx supabase db dump --data-only -f backup.sql`).
- Changing a function's arguments creates a new overload. `drop function` the old
  signature in the same migration and re-run its `grant execute`.

## Adding more job sources

- **Company career pages (best quality):** add boards to `ingest/companies.json`:
  ```json
  [{"ats": "greenhouse", "board": "companyname", "company": "Company GmbH"},
   {"ats": "lever",      "board": "companyname", "company": "Company"},
   {"ats": "ashby",      "board": "companyname", "company": "Company"}]
  ```
  The board name is in the company's careers URL
  (`boards.greenhouse.io/<board>`, `jobs.lever.co/<board>`, `jobs.ashbyhq.com/<board>`).
  For `jobs.eu.lever.co/<board>`, add `"region": "eu"`.
  Only German locations are imported. What counts as German is defined in
  `ingest/cities_de.json` (cities, their other spellings, and the states).
- **More APIs:** write a generator in `ingest/sources.py` that yields the common
  shape, and add it to `collect()` in `ingest/ingest.py`. Candidates are the
  Bundesagentur für Arbeit Jobsuche API and Adzuna (free key).
  Do **not** scrape LinkedIn or other sites whose terms forbid it.

## How the enrichment works (`ingest/enrich.py`)

| Field | Rule |
|---|---|
| English only | `langdetect` on title + description |
| German level | Sentence-level regex → `required` / `nice_to_have` / `not_required` / `not_mentioned` |
| Salary | € ranges, monthly ×12, hourly ignored, sanity 15k–400k |
| Blue Card badge | Salary vs. thresholds in `web/config.js` (**update every January**) |
| Experience / level | "3+ years of experience", title keywords |
| Remote | remote flag + "hybrid", "remote (EU)" phrases |
| Visa / relocation | phrases, with negations ("cannot sponsor") excluded |
| Agency | company name list + "on behalf of our client" |
| Dedupe | sha1(title, company, city), so the same job from two sources shows once |
| Reposts | a job that went inactive and came back gets `repost_count + 1` |

Want better accuracy? Add an optional LLM pass in `enrich()` for the
"key facts" fields. The rules give a free baseline you can measure it against.

## Privacy model

There is no personal data on the server. Saved jobs, applications, seen jobs,
hidden companies and the theme live in the visitor's `localStorage`. The only
anonymous write is the "I got hired" counter, which stores just a timestamp.
There are no cookies and no tracking. If you add analytics, use a cookieless one
(Plausible, Umami, GoatCounter).

## Things to update by hand

- `web/config.js`: `RAISED_THIS_MONTH_EUR` (monthly) and `BLUE_CARD` (each January)
- `supabase/functions/rss/index.ts`: `BLUE_CARD` (each January)

## Making money from it

Three income streams, none of which needs accounts, payments or tracking on your side:

1. **Partner links** in `content/resources.json`. Apply to each program, then paste your
   tracking link into `affiliate_url`. The site labels it "Partner link", adds
   `rel="sponsored"` and shows a disclosure. The private `program` field holds notes on
   each program (commissions, where to apply).
2. **One sponsor slot** (`SPONSOR` in `web/config.js`), sold directly to a relocation
   service, a language school or an employer. It's a plain link with no ad network and no cookies.
3. **Ko-fi support** (already in place).

Google AdSense is left out on purpose: in the EU it requires a certified cookie-consent
banner, which breaks the "no cookies, no banner" promise and earns little at low traffic.

## Content that updates itself

`build/build_site.py` (run daily by `.github/workflows/build-site.yml`) generates:

- **Guides** from `content/blog/*.md`. Write Markdown, push, done. Shortcodes inside posts:
  `{{jobs:tag=no-german,limit=5}}` (live job list, refreshed daily),
  `{{resources:banking}}` (partner cards), `{{stat:no_german_pct}}` (live numbers).
- **Weekly job-market report** (`blog/job-market-YYYY-wNN.html`): live stats, with
  week-over-week changes stored in `content/reports/history.json`.
- **Landing pages** per city and tag (`jobs/city-berlin.html`, `jobs/tag-python.html`)
  for search engines.
- `resources.html`, `blog/feed.xml`, `sitemap.xml`, `robots.txt`.

Setup: add the `SUPABASE_ANON_KEY` secret and a repository *variable* `SITE_URL`,
edit `build/site.json`, then run **Actions → Build site pages** once.
Preview offline: `python build/build_site.py --jobs-file build/sample_jobs.json`
(then delete the generated `web/blog`, `web/jobs` and `content/reports` before you commit).

**Your monthly routine (≈1 hour):** re-check the `reviewed:` date on each guide, update
`RAISED_THIS_MONTH_EUR`, and write one new guide. Topics that get searched: "salary
negotiation in Germany", "probation period", "how to write a German-style CV",
"Werkstudent jobs in English", "jobs in Berlin without German".
