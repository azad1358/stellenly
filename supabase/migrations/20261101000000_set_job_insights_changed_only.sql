-- =====================================================================
-- set_job_insights: only rewrite jobs whose insights changed. The daily run
-- recomputes all ~4,600 jobs; rewriting every row (description, search index,
-- embedding) made a batch exceed the API's 8 s statement timeout.
-- =====================================================================
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
   where j.id = r.id
     and j.insights is distinct from r.insights;
  get diagnostics n = row_count;
  return n;
end;
$$;
revoke all on function public.set_job_insights(jsonb) from public, anon, authenticated;
grant execute on function public.set_job_insights(jsonb) to service_role;
