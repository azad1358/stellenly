-- =====================================================================
-- set_job_facts: corrections from the LLM check in ingest/insights.py.
-- Each value was checked against a quote from the posting (llm_facts.py).
-- Only the fields present in the payload change; nothing is deleted.
-- payload = [{"id": "...", "german_level": "required", "visa_sponsorship": true,
--             "relocation": false, "salary_known": true, "salary_min": 70000, "salary_max": 85000}, ...]
-- =====================================================================
create or replace function public.set_job_facts(payload jsonb)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare n integer;
begin
  update public.jobs j
     set german_level     = coalesce(r.german_level, j.german_level),
         visa_sponsorship = coalesce(r.visa_sponsorship, j.visa_sponsorship),
         relocation       = coalesce(r.relocation, j.relocation),
         salary_min       = case when r.salary_known then r.salary_min else j.salary_min end,
         salary_max       = case when r.salary_known then r.salary_max else j.salary_max end
    from jsonb_to_recordset(payload) as r(id text, german_level text, visa_sponsorship boolean, relocation boolean,
                                          salary_known boolean, salary_min integer, salary_max integer)
   where j.id = r.id;
  get diagnostics n = row_count;
  return n;
end;
$$;

revoke all on function public.set_job_facts(jsonb) from public, anon, authenticated;
grant execute on function public.set_job_facts(jsonb) to service_role;
