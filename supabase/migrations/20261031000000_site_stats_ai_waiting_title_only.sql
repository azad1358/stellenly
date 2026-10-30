-- =====================================================================
-- site_stats: 'ai_waiting' leaves out Amazon's jobs. We only have their
-- title and link (sources.amazon), so the AI never summarises them and
-- they must not wait in the queue counter forever.
-- =====================================================================
create or replace function public.site_stats()
returns jsonb
language sql
stable
security definer           -- needs to count hire_events
set search_path = public
as $$
  select jsonb_build_object(
    'active',      (select count(*) from public.jobs where is_active),
    'total',       (select count(*) from public.jobs),
    'added_today', (select count(*) from public.jobs where is_active and first_seen_at >= now() - interval '24 hours'),
    'ai_waiting',  (select count(*) from public.jobs where is_active and insights->'ai' is null and source <> 'amazon'),
    'hired',       (select count(*) from public.hire_events)
  );
$$;
