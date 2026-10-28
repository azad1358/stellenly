-- =====================================================================
-- Skill check page: a candidate picks a role, rates the 10 skills that
-- postings for it ask for most (1–10), and gets an AI report.
--   role_skill_rows()       build time: title + skills of every job in the database
--                           (also inactive ones, so small roles have enough data)
--   submit_skill_ratings()  stores one browser's ratings for a role, anonymously:
--                           a random id made in the browser, the role, the numbers. No IP, no name.
--   skill_peers()           per skill: other candidates' average and the share of them this
--                           candidate rated higher than — only once 10+ others rated the role
--   take_report_quota()     daily cap on AI reports (Edge Function only)
-- =====================================================================
create or replace function public.role_skill_rows()
returns table (title text, skills jsonb)
language sql
stable
security definer           -- anon may only read active jobs; this returns two columns of all of them
set search_path = public
as $$
  select j.title, j.insights->'skills'
    from public.jobs j
   where jsonb_typeof(j.insights->'skills') = 'array'
     and jsonb_array_length(j.insights->'skills') > 0;
$$;

create table if not exists public.skill_ratings (
  client_id  uuid        not null,
  role       text        not null check (length(role) between 2 and 80),
  levels     jsonb       not null,
  updated_at timestamptz not null default now(),
  primary key (client_id, role)
);
alter table public.skill_ratings enable row level security;  -- no policies: only the functions below touch it

create or replace function public.submit_skill_ratings(p_client uuid, p_role text, p_levels jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_client is null or length(coalesce(p_role, '')) not between 2 and 80
     or jsonb_typeof(p_levels) is distinct from 'object'
     or (select count(*) from jsonb_object_keys(p_levels)) not between 1 and 12
     or exists (select 1 from jsonb_each(p_levels) e
                 where length(e.key) > 40 or jsonb_typeof(e.value) <> 'number'
                    or e.value::numeric not between 1 and 10) then
    raise exception 'invalid ratings';
  end if;
  insert into public.skill_ratings (client_id, role, levels)
  values (p_client, p_role, p_levels)
  on conflict (client_id, role) do update set levels = excluded.levels, updated_at = now();
end;
$$;

create or replace function public.skill_peers(p_role text, p_client uuid default null, p_levels jsonb default '{}')
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  -- "pct": share of the other candidates rated below p_levels (ties count half), 0–100
  with r as (select levels from public.skill_ratings
              where role = p_role and client_id is distinct from p_client),
  per_skill as (
    select e.key, round(avg(e.value::numeric), 1) as avg, count(*) as n,
           round(100.0 * (count(*) filter (where e.value::numeric < (p_levels->>e.key)::numeric)
                          + 0.5 * count(*) filter (where e.value::numeric = (p_levels->>e.key)::numeric)) / count(*)) as pct
      from r, jsonb_each(r.levels) e
     group by e.key
  )
  select jsonb_build_object(
    'n', (select count(*) from r),
    'skills', case when (select count(*) from r) >= 10
                   then (select jsonb_object_agg(key, jsonb_build_object('avg', avg, 'n', n, 'pct', pct)) from per_skill)
              end);
$$;

create table if not exists public.report_quota (
  day date    primary key,
  n   integer not null default 0
);
alter table public.report_quota enable row level security;

create or replace function public.take_report_quota(p_max integer)
returns boolean
language sql
security definer
set search_path = public
as $$
  insert into public.report_quota as q (day, n) values (current_date, 1)
  on conflict (day) do update set n = q.n + 1
  returning n <= p_max;
$$;

revoke all on function public.role_skill_rows()                         from public;
revoke all on function public.submit_skill_ratings(uuid, text, jsonb)   from public;
revoke all on function public.skill_peers(text, uuid, jsonb)            from public;
revoke all on function public.take_report_quota(integer)                from public, anon, authenticated;
grant execute on function public.role_skill_rows()                       to anon, authenticated;
grant execute on function public.submit_skill_ratings(uuid, text, jsonb) to anon, authenticated;
grant execute on function public.skill_peers(text, uuid, jsonb)          to anon, authenticated;
grant execute on function public.take_report_quota(integer)              to service_role;
