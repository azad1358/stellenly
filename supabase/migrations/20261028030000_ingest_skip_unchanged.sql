-- =====================================================================
-- ingest_jobs: rewrite only new or changed jobs. Every run sees ~4,000
-- jobs that mostly didn't change; rewriting them all rebuilt the search
-- vector (full description) each time and hit the 8 s statement timeout.
-- An unchanged active job now only gets last_seen_at = now(), which
-- doesn't touch fts (~6x cheaper).
-- =====================================================================
create or replace function public.ingest_jobs(payload jsonb)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  n integer;
  m integer;
begin
  insert into public.jobs as j (
    id, source, source_id, url, title, company, location, city, remote_type,
    description, tags, tags_text, job_types, german_level, visa_sponsorship,
    relocation, salary_min, salary_max, years_experience, seniority, is_agency, posted_at
  )
  select
    r.id, r.source, r.source_id, r.url, r.title, r.company, r.location, r.city,
    coalesce(r.remote_type, 'unknown'), r.description,
    coalesce(r.tags, '{}'), array_to_string(coalesce(r.tags, '{}'), ' '),
    coalesce(r.job_types, '{}'), coalesce(r.german_level, 'not_mentioned'),
    coalesce(r.visa_sponsorship, false), coalesce(r.relocation, false),
    r.salary_min, r.salary_max, r.years_experience,
    coalesce(r.seniority, 'unspecified'), coalesce(r.is_agency, false),
    coalesce(r.posted_at, now())
  from jsonb_to_recordset(payload) as r(
    id text, source text, source_id text, url text, title text, company text,
    location text, city text, remote_type text, description text, tags text[],
    job_types text[], german_level text, visa_sponsorship boolean, relocation boolean,
    salary_min integer, salary_max integer, years_experience integer,
    seniority text, is_agency boolean, posted_at timestamptz
  )
  on conflict (id) do update set
    source           = excluded.source,
    source_id        = excluded.source_id,
    url              = excluded.url,
    location         = excluded.location,
    remote_type      = excluded.remote_type,
    description      = excluded.description,
    tags             = excluded.tags,
    tags_text        = excluded.tags_text,
    job_types        = excluded.job_types,
    german_level     = excluded.german_level,
    visa_sponsorship = excluded.visa_sponsorship,
    relocation       = excluded.relocation,
    salary_min       = excluded.salary_min,
    salary_max       = excluded.salary_max,
    years_experience = excluded.years_experience,
    seniority        = excluded.seniority,
    is_agency        = excluded.is_agency,
    -- a job that comes back after being inactive is a repost
    repost_count     = j.repost_count + case when j.is_active then 0 else 1 end,
    posted_at        = case when j.is_active then least(j.posted_at, excluded.posted_at)
                            else excluded.posted_at end,
    last_seen_at     = now(),
    is_active        = true
  where not j.is_active
     or excluded.posted_at < j.posted_at
     or (j.source, j.source_id, j.url, j.location, j.remote_type, j.description, j.tags, j.job_types,
         j.german_level, j.visa_sponsorship, j.relocation, j.salary_min, j.salary_max,
         j.years_experience, j.seniority, j.is_agency)
        is distinct from
        (excluded.source, excluded.source_id, excluded.url, excluded.location, excluded.remote_type,
         excluded.description, excluded.tags, excluded.job_types, excluded.german_level,
         excluded.visa_sponsorship, excluded.relocation, excluded.salary_min, excluded.salary_max,
         excluded.years_experience, excluded.seniority, excluded.is_agency);
  get diagnostics n = row_count;

  -- Unchanged active jobs: just mark them as seen (rows written above already have now()).
  update public.jobs
     set last_seen_at = now()
   where id in (select p->>'id' from jsonb_array_elements(payload) p)
     and last_seen_at < now();
  get diagnostics m = row_count;

  return n + m;
end;
$$;
