-- =====================================================================
-- Job insights: peer statistics and hints per job ("salary unusually high
-- for an internship", "pays more than 75% of similar jobs", ...).
-- Computed daily by ingest/insights.py (embeddings + similar jobs) and
-- written with set_job_insights(). Existing rows and data are untouched.
-- =====================================================================

alter table public.jobs add column if not exists insights jsonb;

-- Called by the insights job (service_role only).
-- payload = [{"id": "...", "insights": {...}}, ...]
create or replace function public.set_job_insights(payload jsonb)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare n integer;
begin
  update public.jobs j
     set insights = r.insights
    from jsonb_to_recordset(payload) as r(id text, insights jsonb)
   where j.id = r.id;
  get diagnostics n = row_count;
  return n;
end;
$$;

-- Similar jobs for the "Compared with similar jobs" panel (ids come from insights.similar).
create or replace function public.jobs_by_ids(p_ids text[])
returns jsonb
language sql
stable
set search_path = public
as $$
  select coalesce(jsonb_agg(jsonb_build_object(
           'id', id, 'url', url, 'title', title, 'company', company, 'city', city,
           'salary_min', salary_min, 'salary_max', salary_max, 'german_level', german_level,
           'seniority', seniority, 'posted_at', posted_at)
         order by array_position(p_ids, id)), '[]'::jsonb)
    from public.jobs
   where is_active and id = any(p_ids[1:20]);
$$;

-- search_jobs: unchanged except that each item now includes 'insights'.
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
        'first_seen_at', first_seen_at, 'repost_count', repost_count,
        'insights', insights
      ))
      from page), '[]'::jsonb)
  );
$$;

revoke all on function public.set_job_insights(jsonb) from public, anon, authenticated;
grant execute on function public.set_job_insights(jsonb) to service_role;
grant execute on function public.jobs_by_ids(text[]) to anon, authenticated;
