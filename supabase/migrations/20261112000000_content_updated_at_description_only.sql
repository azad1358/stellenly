-- jobs.content_updated_at now moves only when the description changes. "Job insights" rewrites the insights of
-- thousands of jobs on every run (similar jobs shift as new jobs arrive), so tracking insights made build/job_pages.py
-- re-download most descriptions anyway. Job pages now read the small parts of insights they show (hints, similar)
-- on every build and keep only descriptions in the cache.

create or replace function public.jobs_touch_content_updated_at() returns trigger
language plpgsql as $$
begin
  if tg_op = 'INSERT' or new.description is distinct from old.description then
    new.content_updated_at := now();
  else
    new.content_updated_at := old.content_updated_at;
  end if;
  return new;
end $$;
