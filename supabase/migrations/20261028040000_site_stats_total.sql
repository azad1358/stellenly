-- =====================================================================
-- site_stats: also 'total', every job listed so far (active or not),
-- shown next to "Open roles" on the main page.
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
    'hired',       (select count(*) from public.hire_events)
  );
$$;
