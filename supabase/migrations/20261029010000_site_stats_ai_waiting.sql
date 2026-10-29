-- =====================================================================
-- site_stats: also 'ai_waiting', open jobs the AI hasn't summarised yet
-- (the free LLM quota covers a few hundred a day; insights.py works
-- through the rest run by run). Shown on the main page before
-- "People hired".
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
    'ai_waiting',  (select count(*) from public.jobs where is_active and insights->'ai' is null),
    'hired',       (select count(*) from public.hire_events)
  );
$$;
