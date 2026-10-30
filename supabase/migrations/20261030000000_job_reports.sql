-- =====================================================================
-- Crowd reports: visitors can flag a job whose posting is gone from the
-- company's careers page while its API still lists it. Anonymous — only
-- counters per job, no visitor data. Other visitors can answer "still
-- open" (confirm_open), which cancels a report: net = reports − open.
-- The card is flagged while net > 0; after each import, ingest.py hides
-- jobs with net >= REPORT_THRESHOLD (deactivate_reported), and
-- ingest_jobs no longer brings such a job back when its API keeps
-- listing it.
-- =====================================================================
alter table public.jobs
  add column if not exists report_count       integer not null default 0,
  add column if not exists last_reported_at   timestamptz,
  add column if not exists open_count         integer not null default 0,  -- "still open" answers
  add column if not exists last_confirmed_at  timestamptz,
  add column if not exists reported_closed_at timestamptz;  -- set when hidden because of reports

-- Called by the website (anon key). One call = +1, at most one counted report per job
-- every 10 minutes (a burst of clicks can't hide a job). Returns the new count, or null if not counted.
create or replace function public.report_job(p_id text)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  n integer;
begin
  update public.jobs
     set report_count = report_count + 1, last_reported_at = now()
   where id = p_id and is_active
     and (last_reported_at is null or last_reported_at < now() - interval '10 minutes')
  returning report_count into n;
  return n;
end;
$$;

-- Called by the website: a visitor says the job is still open. Same limits as report_job.
create or replace function public.confirm_open(p_id text)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  n integer;
begin
  update public.jobs
     set open_count = open_count + 1, last_confirmed_at = now()
   where id = p_id and is_active
     and (last_confirmed_at is null or last_confirmed_at < now() - interval '10 minutes')
  returning open_count into n;
  return n;
end;
$$;

-- Called by the ingester after a run: hide the jobs whose reports outnumber the "still open" answers by p_threshold.
create or replace function public.deactivate_reported(p_threshold integer)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  n integer;
begin
  update public.jobs
     set is_active = false, reported_closed_at = now(), last_checked_at = now()
   where is_active and report_count - open_count >= greatest(p_threshold, 1);
  get diagnostics n = row_count;
  return n;
end;
$$;

revoke all on function public.report_job(text) from public;
revoke all on function public.confirm_open(text) from public;
revoke all on function public.deactivate_reported(integer) from public, anon, authenticated;
grant execute on function public.report_job(text) to anon, authenticated;
grant execute on function public.confirm_open(text) to anon, authenticated;
grant execute on function public.deactivate_reported(integer) to service_role;

-- ingest_jobs: as before, but a job hidden because of reports stays hidden even though its API still lists it.
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
  where j.reported_closed_at is null and (not j.is_active
     or excluded.posted_at < j.posted_at
     or (j.source, j.source_id, j.url, j.location, j.remote_type, j.description, j.tags, j.job_types,
         j.german_level, j.visa_sponsorship, j.relocation, j.salary_min, j.salary_max,
         j.years_experience, j.seniority, j.is_agency)
        is distinct from
        (excluded.source, excluded.source_id, excluded.url, excluded.location, excluded.remote_type,
         excluded.description, excluded.tags, excluded.job_types, excluded.german_level,
         excluded.visa_sponsorship, excluded.relocation, excluded.salary_min, excluded.salary_max,
         excluded.years_experience, excluded.seniority, excluded.is_agency));
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

-- search_jobs: each item also returns report_count and open_count (the card's flag).
create or replace function public.search_jobs(
  p_q               text    default null,
  p_tags            text[]  default null,  -- job must have ALL of these tags
  p_city            text    default null,
  p_remote          text[]  default null,  -- remote_type values
  p_german          text[]  default null,  -- german_level values
  p_seniority       text[]  default null,
  p_has_salary      boolean default false,
  p_min_salary      integer default null,  -- yearly EUR (used for Blue Card filter too)
  p_visa            boolean default false,
  p_relocation      boolean default false,
  p_direct_only     boolean default false, -- hide recruiting agencies
  p_max_years       integer default null,  -- max "years of experience" asked
  p_days            integer default null,  -- posted within N days
  p_exclude_terms   text[]  default null,  -- hide titles containing these words
  p_hide_companies  text[]  default null,
  p_sort            text    default 'newest', -- 'newest' | 'relevance' | 'salary'
  p_limit           integer default 20,
  p_offset          integer default 0,
  p_scope           text    default 'all'     -- 'title' | 'all' (see above)
)
returns jsonb
language sql
stable
set search_path = public
as $$
  with params as (
    select case when nullif(trim(p_q), '') is null then null
                else websearch_to_tsquery('english', p_q) end as tsq,
           case when nullif(trim(p_q), '') is null then null
                else phraseto_tsquery('english', p_q) end as phrase
  ),
  matched as (
    select j.*,
           case when params.tsq is null then 0 else ts_rank(j.fts, params.tsq) end as rank,
           -- weights A/B = title, company, tags (see the fts column); C = description
           (params.tsq is null or ts_filter(j.fts, '{a,b}') @@ params.tsq) as strong,
           case when params.tsq is null then 0
                when ts_filter(j.fts, '{a}') @@ params.phrase then 0
                when ts_filter(j.fts, '{a}') @@ params.tsq then 1
                when ts_filter(j.fts, '{a,b}') @@ params.tsq then 2
                else 3 end as tier,
           coalesce(pop.score, 0) as popularity,
           coalesce(pop.opens, 0) as views,
           coalesce(pop.applies, 0) as apply_clicks
      from public.jobs j
     cross join params
      left join lateral (
        select sum(case when s.day >= current_date - 14 then s.applies * 3 + s.opens end)::int as score,  -- Apply = 3 opens
               sum(s.opens)::int as opens, sum(s.applies)::int as applies                                     -- all-time totals
          from public.job_daily_stats s
         where s.job_id = j.id
      ) pop on true
     where j.is_active
       and (params.tsq is null or j.fts @@ params.tsq)
       and (p_tags is null or cardinality(p_tags) = 0 or j.tags @> p_tags)
       and (nullif(p_city, '') is null or j.city = p_city)
       and (p_remote is null or cardinality(p_remote) = 0 or j.remote_type = any(p_remote))
       and (p_german is null or cardinality(p_german) = 0 or j.german_level = any(p_german))
       and (p_seniority is null or cardinality(p_seniority) = 0 or j.seniority = any(p_seniority))
       and (not coalesce(p_has_salary, false) or j.salary_min is not null)
       and (p_min_salary is null or coalesce(j.salary_max, j.salary_min) >= p_min_salary)
       and (not coalesce(p_visa, false) or j.visa_sponsorship)
       and (not coalesce(p_relocation, false) or j.relocation)
       and (not coalesce(p_direct_only, false) or not j.is_agency)
       and (p_max_years is null or j.years_experience is null or j.years_experience <= p_max_years)
       and (p_days is null or j.posted_at >= now() - make_interval(days => p_days))
       and (p_exclude_terms is null or not exists (
              select 1 from unnest(p_exclude_terms) t
               where nullif(trim(t), '') is not null and j.title ilike '%' || trim(t) || '%'))
       and (p_hide_companies is null or not (j.company = any(p_hide_companies)))
  ),
  filtered as (
    select * from matched where coalesce(p_scope, 'all') <> 'title' or strong
  ),
  page as (
    select * from filtered
     order by
       tier,
       case when p_sort = 'relevance' then rank end desc nulls last,
       case when p_sort = 'salary' then coalesce(salary_max, salary_min) end desc nulls last,
       case when p_sort = 'popular' then popularity end desc nulls last,
       posted_at desc,
       id
     limit least(greatest(coalesce(p_limit, 20), 1), 100)
     offset greatest(coalesce(p_offset, 0), 0)
  )
  select jsonb_build_object(
    'total', (select count(*) from filtered),
    'strong_total', (select count(*) from filtered where strong),
    'all_total', (select count(*) from matched),
    'items', coalesce((
      select jsonb_agg(jsonb_build_object(
        'id', id, 'url', url, 'title', title, 'company', company, 'city', city,
        'location', location, 'remote_type', remote_type,
        'snippet', left(description, 600),
        'tags', tags, 'job_types', job_types, 'german_level', german_level,
        'visa_sponsorship', visa_sponsorship, 'relocation', relocation,
        'salary_min', salary_min, 'salary_max', salary_max,
        'years_experience', years_experience, 'seniority', seniority,
        'is_agency', is_agency, 'posted_at', posted_at,
        'first_seen_at', first_seen_at, 'repost_count', repost_count,
        'insights', insights,
        'popularity', popularity,
        'views', views,
        'apply_clicks', apply_clicks,
        'report_count', report_count,
        'open_count', open_count,
        'match', case when strong then 'title' else 'text' end
      ))
      from page), '[]'::jsonb)
  );
$$;

grant execute on function public.search_jobs(text, text[], text, text[], text[], text[], boolean, integer, boolean, boolean, boolean, integer, integer, text[], text[], text, integer, integer, text) to anon, authenticated;
