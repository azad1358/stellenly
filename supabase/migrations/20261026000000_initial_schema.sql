-- =====================================================================
-- Jobs in Germany (English) — baseline schema (migration 1).
-- Never edit this file once it is applied: add a new migration instead
-- (`supabase migration new <name>`). See "Database changes" in README.md.
-- Public visitors use the anon key: they can only READ active jobs and
-- call the search/facet/stats functions. Writing is done by the ingester
-- with the service_role key (kept secret in GitHub Actions).
-- =====================================================================

create extension if not exists pg_trgm;

-- ---------------------------------------------------------------------
-- Jobs
-- ---------------------------------------------------------------------
create table if not exists public.jobs (
  id                text primary key,            -- dedupe hash (title|company|city)
  source            text not null,               -- 'arbeitnow', 'greenhouse:acme', ...
  source_id         text,
  url               text not null,               -- original posting (apply link)
  title             text not null,
  company           text not null,
  location          text,
  city              text,
  remote_type       text not null default 'unknown'
                    check (remote_type in ('remote_de','remote_eu','hybrid','onsite','unknown')),
  description       text,                        -- plain text, truncated
  tags              text[] not null default '{}',
  tags_text         text not null default '',    -- tags joined (for full-text search)
  job_types         text[] not null default '{}',
  german_level      text not null default 'not_mentioned'
                    check (german_level in ('not_required','nice_to_have','required','not_mentioned')),
  visa_sponsorship  boolean not null default false,
  relocation        boolean not null default false,
  salary_min        integer,                     -- yearly EUR, gross
  salary_max        integer,
  years_experience  integer,                     -- minimum years asked for
  seniority         text not null default 'unspecified'
                    check (seniority in ('intern','junior','mid','senior','lead','unspecified')),
  is_agency         boolean not null default false,
  posted_at         timestamptz not null default now(),
  first_seen_at     timestamptz not null default now(),
  last_seen_at      timestamptz not null default now(),
  last_checked_at   timestamptz,
  is_active         boolean not null default true,
  repost_count      integer not null default 0,
  fts tsvector generated always as (
        setweight(to_tsvector('english', coalesce(title, '')),       'A')
     || setweight(to_tsvector('english', coalesce(company, '')),     'B')
     || setweight(to_tsvector('english', coalesce(tags_text, '')),   'B')
     || setweight(to_tsvector('english', coalesce(description, '')), 'C')
  ) stored
);

create index if not exists jobs_fts_idx        on public.jobs using gin (fts);
create index if not exists jobs_tags_idx       on public.jobs using gin (tags);
create index if not exists jobs_active_posted  on public.jobs (is_active, posted_at desc);
create index if not exists jobs_city_idx       on public.jobs (city);
create index if not exists jobs_checked_idx    on public.jobs (last_checked_at nulls first) where is_active;

alter table public.jobs enable row level security;

drop policy if exists "public can read active jobs" on public.jobs;
create policy "public can read active jobs"
  on public.jobs for select
  to anon, authenticated
  using (is_active);

-- ---------------------------------------------------------------------
-- "I got hired" counter — stores only a timestamp. No personal data.
-- ---------------------------------------------------------------------
create table if not exists public.hire_events (
  id         bigint generated always as identity primary key,
  created_at timestamptz not null default now()
);
alter table public.hire_events enable row level security;  -- no policies: not readable/writable directly

create or replace function public.record_hire()
returns void
language sql
security definer
set search_path = public
as $$
  insert into public.hire_events default values;
$$;

-- ---------------------------------------------------------------------
-- Ingest: upsert a batch of jobs (called by the ingester, service_role only)
-- payload = JSON array of job objects (keys = column names above)
-- ---------------------------------------------------------------------
create or replace function public.ingest_jobs(payload jsonb)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  n integer;
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
    is_active        = true;

  get diagnostics n = row_count;
  return n;
end;
$$;

-- Hide jobs that are too old (default 45 days).
create or replace function public.expire_jobs(max_age_days integer default 45)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare n integer;
begin
  update public.jobs
     set is_active = false
   where is_active
     and posted_at < now() - make_interval(days => max_age_days);
  get diagnostics n = row_count;
  return n;
end;
$$;

-- Record the result of the dead-link checker.
create or replace function public.mark_checked(alive_ids text[], dead_ids text[])
returns void
language sql
security definer
set search_path = public
as $$
  update public.jobs set last_checked_at = now()
   where id = any(coalesce(alive_ids, '{}'));
  update public.jobs set last_checked_at = now(), is_active = false
   where id = any(coalesce(dead_ids, '{}'));
$$;

-- ---------------------------------------------------------------------
-- Public read functions
-- ---------------------------------------------------------------------

-- Main search. All filters optional. Returns {"total": n, "items": [...]}
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
  p_offset          integer default 0
)
returns jsonb
language sql
stable
set search_path = public
as $$
  with params as (
    select case when nullif(trim(p_q), '') is null then null
                else websearch_to_tsquery('english', p_q) end as tsq
  ),
  filtered as (
    select j.*,
           case when params.tsq is null then 0 else ts_rank(j.fts, params.tsq) end as rank
      from public.jobs j, params
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
  page as (
    select * from filtered
     order by
       case when p_sort = 'relevance' then rank end desc nulls last,
       case when p_sort = 'salary' then coalesce(salary_max, salary_min) end desc nulls last,
       posted_at desc
     limit least(greatest(coalesce(p_limit, 20), 1), 100)
     offset greatest(coalesce(p_offset, 0), 0)
  )
  select jsonb_build_object(
    'total', (select count(*) from filtered),
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
        'first_seen_at', first_seen_at, 'repost_count', repost_count
      ))
      from page), '[]'::jsonb)
  );
$$;

-- Popular tags and cities for the filter chips.
create or replace function public.facets(p_limit integer default 30)
returns jsonb
language sql
stable
set search_path = public
as $$
  select jsonb_build_object(
    'tags', coalesce((
      select jsonb_agg(jsonb_build_object('tag', tag, 'count', c))
        from (select tag, count(*) c
                from public.jobs, unnest(tags) tag
               where is_active
               group by tag order by c desc limit p_limit) t), '[]'::jsonb),
    'cities', coalesce((
      select jsonb_agg(jsonb_build_object('city', city, 'count', c))
        from (select city, count(*) c
                from public.jobs
               where is_active and city is not null and city <> ''
               group by city order by c desc limit p_limit) t), '[]'::jsonb)
  );
$$;

-- Header numbers: active jobs, added today, people hired.
create or replace function public.site_stats()
returns jsonb
language sql
stable
security definer           -- needs to count hire_events
set search_path = public
as $$
  select jsonb_build_object(
    'active',      (select count(*) from public.jobs where is_active),
    'added_today', (select count(*) from public.jobs where is_active and first_seen_at >= now() - interval '24 hours'),
    'hired',       (select count(*) from public.hire_events)
  );
$$;

-- ---------------------------------------------------------------------
-- Permissions
-- ---------------------------------------------------------------------
revoke all on function public.ingest_jobs(jsonb)            from public, anon, authenticated;
revoke all on function public.expire_jobs(integer)          from public, anon, authenticated;
revoke all on function public.mark_checked(text[], text[])  from public, anon, authenticated;
grant execute on function public.ingest_jobs(jsonb)           to service_role;
grant execute on function public.expire_jobs(integer)         to service_role;
grant execute on function public.mark_checked(text[], text[]) to service_role;

grant execute on function public.search_jobs(text, text[], text, text[], text[], text[], boolean, integer,
  boolean, boolean, boolean, integer, integer, text[], text[], text, integer, integer) to anon, authenticated;
grant execute on function public.facets(integer)   to anon, authenticated;
grant execute on function public.site_stats()      to anon, authenticated;
grant execute on function public.record_hire()     to anon, authenticated;
