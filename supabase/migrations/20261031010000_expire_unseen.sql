-- =====================================================================
-- expire_jobs: a job stays online as long as its source still lists it.
-- Before, every job was hidden 45 days after it was posted, although the
-- employer's own career page still showed it (most roles take longer to
-- fill). Now a job is hidden when no import has seen it for unseen_days
-- (its source failed or was read only in part); only Arbeitnow, which
-- copies jobs from other sites and can keep stale ones, keeps the
-- 45-day limit on the posting date. Removed jobs still disappear right
-- away through deactivate_unseen, the dead-link check and crowd reports.
-- =====================================================================
drop function if exists public.expire_jobs(integer);

create or replace function public.expire_jobs(max_age_days integer default 45, unseen_days integer default 7)
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
     and (last_seen_at < now() - make_interval(days => unseen_days)
          or (source = 'arbeitnow' and posted_at < now() - make_interval(days => max_age_days)));
  get diagnostics n = row_count;
  return n;
end;
$$;

revoke all on function public.expire_jobs(integer, integer) from public, anon, authenticated;
grant execute on function public.expire_jobs(integer, integer) to service_role;

-- One-time: bring back the jobs the old rule hid although their employer still lists them (seen by the last
-- import). Each import had switched them on (repost_count + 1) and the 45-day rule off again, so their
-- repost_count only counts that loop: reset it. Jobs hidden because of crowd reports stay hidden.
update public.jobs
   set is_active = true, repost_count = 0
 where not is_active
   and source <> 'arbeitnow'
   and posted_at < now() - interval '45 days'
   and last_seen_at > now() - interval '1 day'
   and reported_closed_at is null;
