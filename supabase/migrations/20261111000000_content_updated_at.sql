-- jobs.content_updated_at: when a job's description or insights last changed.
-- build/job_pages.py keeps descriptions + insights from the previous build in the Actions cache and downloads
-- only the jobs whose content_updated_at moved, instead of ~40 MB of text on every deploy (Supabase egress quota).
-- last_seen_at and the other columns are re-read on every build anyway, so they don't touch this column.

alter table public.jobs add column if not exists content_updated_at timestamptz not null default now();

create or replace function public.jobs_touch_content_updated_at() returns trigger
language plpgsql as $$
begin
  if tg_op = 'INSERT' then
    new.content_updated_at := now();
  elsif new.description is distinct from old.description or new.insights is distinct from old.insights then
    new.content_updated_at := now();
  else
    new.content_updated_at := old.content_updated_at;
  end if;
  return new;
end $$;

drop trigger if exists jobs_content_updated_at on public.jobs;
create trigger jobs_content_updated_at before insert or update on public.jobs
  for each row execute function public.jobs_touch_content_updated_at();
