-- =====================================================================
-- job_map: a 2D position for every open job, from its embedding (UMAP in
-- ingest/insights.py), so that similar jobs lie close together on the
-- website's job map (map.html). Replaced completely by every insights run;
-- the website build (build_site.py) reads it into web/data/job-map.json.
-- =====================================================================
create table if not exists public.job_map (
  job_id     text primary key,
  x          real not null,
  y          real not null,
  updated_at timestamptz not null default now()
);
alter table public.job_map enable row level security;
drop policy if exists "job_map readable" on public.job_map;
create policy "job_map readable" on public.job_map for select to anon, authenticated using (true);

-- payload = [{"id": "...", "x": 0.12, "y": -3.4}, ...]: all positions of this run, in one statement
create or replace function public.set_job_map(payload jsonb)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare n integer;
begin
  delete from public.job_map where true;
  insert into public.job_map (job_id, x, y)
  select r.id, r.x, r.y from jsonb_to_recordset(payload) as r(id text, x real, y real);
  get diagnostics n = row_count;
  return n;
end;
$$;
revoke all on function public.set_job_map(jsonb) from public, anon, authenticated;
grant execute on function public.set_job_map(jsonb) to service_role;
