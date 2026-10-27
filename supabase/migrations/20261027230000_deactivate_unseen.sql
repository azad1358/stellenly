-- =====================================================================
-- deactivate_unseen: hide jobs that are no longer listed at their source.
-- Called by the ingester after a run, only with sources it read completely
-- (all Arbeitnow pages, or a company board fetched without errors). Rows
-- are only hidden (is_active = false), never deleted.
-- Safety: if more than p_max_share of a run's active rows would be hidden,
-- nothing happens and -1 is returned (a broken source must not empty the site).
-- =====================================================================
create or replace function public.deactivate_unseen(p_sources text[], p_before timestamptz, p_max_share real default 0.6)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  candidates integer;
  total integer;
begin
  select count(*) filter (where last_seen_at < p_before), count(*)
    into candidates, total
    from public.jobs
   where is_active and source = any(p_sources);
  if total = 0 or candidates > total * p_max_share then
    return -1;
  end if;
  update public.jobs
     set is_active = false, last_checked_at = now()
   where is_active and source = any(p_sources) and last_seen_at < p_before;
  return candidates;
end;
$$;

revoke all on function public.deactivate_unseen(text[], timestamptz, real) from public, anon, authenticated;
grant execute on function public.deactivate_unseen(text[], timestamptz, real) to service_role;
