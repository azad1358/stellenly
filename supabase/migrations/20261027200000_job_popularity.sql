-- =====================================================================
-- Job popularity: anonymous counts per job and day of popup opens and
-- Apply clicks. No visitor data at all (no IP, no id, no cookie) — only
-- "job X was opened N times on day D". Used for the "Most popular" sort
-- (last 14 days, Apply clicks weighted 3x) and the "Popular" badge.
-- =====================================================================

create table if not exists public.job_daily_stats (
  job_id  text    not null,
  day     date    not null default current_date,
  opens   integer not null default 0,
  applies integer not null default 0,
  primary key (job_id, day)
);
create index if not exists job_daily_stats_day_idx on public.job_daily_stats (day);
alter table public.job_daily_stats enable row level security;
-- The counts are anonymous totals, so anyone may read them (search_jobs needs this); writes only via record_job_event.
drop policy if exists "anyone can read job popularity" on public.job_daily_stats;
create policy "anyone can read job popularity" on public.job_daily_stats for select to anon, authenticated using (true);

-- Called by the website (anon key). Only 'open' / 'apply' for active jobs; one call = +1.
create or replace function public.record_job_event(p_id text, p_kind text)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_kind not in ('open', 'apply') then
    return;
  end if;
  if not exists (select 1 from public.jobs where id = p_id and is_active) then
    return;
  end if;
  insert into public.job_daily_stats as s (job_id, day, opens, applies)
  values (p_id, current_date, (p_kind = 'open')::int, (p_kind = 'apply')::int)
  on conflict (job_id, day) do update
    set opens   = s.opens   + (p_kind = 'open')::int,
        applies = s.applies + (p_kind = 'apply')::int;
end;
$$;

-- search_jobs: new sort 'popular'; each item also returns its 'popularity' score.
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
           case when params.tsq is null then 0 else ts_rank(j.fts, params.tsq) end as rank,
           coalesce(pop.score, 0) as popularity
      from public.jobs j
     cross join params
      left join lateral (
        select sum(s.applies * 3 + s.opens)::int as score   -- an Apply click counts 3x an open
          from public.job_daily_stats s
         where s.job_id = j.id and s.day >= current_date - 14
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
  page as (
    select * from filtered
     order by
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
        'popularity', popularity
      ))
      from page), '[]'::jsonb)
  );
$$;

grant execute on function public.record_job_event(text, text) to anon, authenticated;
