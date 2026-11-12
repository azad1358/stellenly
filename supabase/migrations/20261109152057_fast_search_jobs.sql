CREATE OR REPLACE FUNCTION public.search_jobs(p_q text DEFAULT NULL::text, p_tags text[] DEFAULT NULL::text[], p_city text DEFAULT NULL::text, p_remote text[] DEFAULT NULL::text[], p_german text[] DEFAULT NULL::text[], p_seniority text[] DEFAULT NULL::text[], p_has_salary boolean DEFAULT false, p_min_salary integer DEFAULT NULL::integer, p_visa boolean DEFAULT false, p_relocation boolean DEFAULT false, p_direct_only boolean DEFAULT false, p_max_years integer DEFAULT NULL::integer, p_days integer DEFAULT NULL::integer, p_exclude_terms text[] DEFAULT NULL::text[], p_hide_companies text[] DEFAULT NULL::text[], p_sort text DEFAULT 'newest'::text, p_limit integer DEFAULT 20, p_offset integer DEFAULT 0, p_scope text DEFAULT 'all'::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
 SET search_path TO 'public'
AS $function$
declare
  v_tsq    tsquery := case when nullif(trim(p_q), '') is null then null
                           else websearch_to_tsquery('english', p_q) end;
  v_phrase tsquery := case when nullif(trim(p_q), '') is null then null
                           else phraseto_tsquery('english', p_q) end;
  v_result jsonb;
begin
  -- EXECUTE plans with the actual values every time: unused filters drop out
  -- and the full-text index is used when there is a search query.
  execute $q$
    with pop14 as (       -- popularity for the "popular" sort: Apply = 3 opens, last 14 days
      select s.job_id, sum(s.applies * 3 + s.opens)::int as score
        from public.job_daily_stats s
       where $16 = 'popular' and s.day >= current_date - 14
       group by s.job_id
    ),
    matched as materialized (
      select j.id, j.is_agency, j.posted_at,
             coalesce(j.salary_max, j.salary_min) as sal,
             case when $1 is not null and $16 = 'relevance' then ts_rank(j.fts, $1) end as rank,
             -- weights A/B = title, company, tags; C = description
             ($1 is null or ts_filter(j.fts, '{a,b}') @@ $1) as strong,
             case when $1 is null then 0
                  when ts_filter(j.fts, '{a}') @@ $2 then 0
                  when ts_filter(j.fts, '{a}') @@ $1 then 1
                  when ts_filter(j.fts, '{a,b}') @@ $1 then 2
                  else 3 end as tier
        from public.jobs j
       where j.is_active
         and ($1 is null or j.fts @@ $1)
         and ($3 is null or cardinality($3) = 0 or j.tags @> $3)
         and (nullif($4, '') is null or j.city = $4)
         and ($5 is null or cardinality($5) = 0 or j.remote_type = any($5))
         and ($6 is null or cardinality($6) = 0 or j.german_level = any($6))
         and ($7 is null or cardinality($7) = 0 or j.seniority = any($7))
         and (not coalesce($8, false) or j.salary_min is not null)
         and ($9 is null or coalesce(j.salary_max, j.salary_min) >= $9)
         and (not coalesce($10, false) or j.visa_sponsorship)
         and (not coalesce($11, false) or j.relocation)
         and (not coalesce($12, false) or not j.is_agency)
         and ($13 is null or j.years_experience is null or j.years_experience <= $13)
         and ($14 is null or j.posted_at >= now() - make_interval(days => $14))
         and ($15 is null or not exists (
                select 1 from unnest($15) t
                 where nullif(trim(t), '') is not null and j.title ilike '%' || trim(t) || '%'))
         and ($20 is null or not (j.company = any($20)))
    ),
    filtered as materialized (
      select m.*, coalesce(p.score, 0) as popularity
        from matched m left join pop14 p on p.job_id = m.id
       where coalesce($19, 'all') <> 'title' or m.strong
    ),
    page as (
      select * from filtered
       order by
         tier,
         is_agency,  -- direct employers first, recruiting agencies after them (in every sort)
         case when $16 = 'relevance' then rank end desc nulls last,
         case when $16 = 'salary' then sal end desc nulls last,
         case when $16 = 'popular' then popularity end desc nulls last,
         posted_at desc,
         id
       limit least(greatest(coalesce($17, 20), 1), 100)
       offset greatest(coalesce($18, 0), 0)
    ),
    page_stats as (       -- popularity (14 days) + all-time totals, only for the jobs shown
      select s.job_id,
             sum(case when s.day >= current_date - 14 then s.applies * 3 + s.opens end)::int as score,
             sum(s.opens)::int as opens, sum(s.applies)::int as applies
        from public.job_daily_stats s
       where s.job_id in (select id from page)
       group by s.job_id
    )
    select jsonb_build_object(
      'total', (select count(*) from filtered),
      'strong_total', (select count(*) from filtered where strong),
      'all_total', (select count(*) from matched),
      'items', coalesce((
        select jsonb_agg(jsonb_build_object(
          'id', j.id, 'url', j.url, 'title', j.title, 'company', j.company, 'city', j.city,
          'location', j.location, 'remote_type', j.remote_type,
          'snippet', left(j.description, 600),
          'tags', j.tags, 'job_types', j.job_types, 'german_level', j.german_level,
          'visa_sponsorship', j.visa_sponsorship, 'relocation', j.relocation,
          'salary_min', j.salary_min, 'salary_max', j.salary_max,
          'years_experience', j.years_experience, 'seniority', j.seniority,
          'is_agency', j.is_agency, 'posted_at', j.posted_at,
          'first_seen_at', j.first_seen_at, 'repost_count', j.repost_count,
          'insights', j.insights,
          'popularity', coalesce(ps.score, 0),
          'views', coalesce(ps.opens, 0),
          'apply_clicks', coalesce(ps.applies, 0),
          'report_count', j.report_count,
          'open_count', j.open_count,
          'match', case when p.strong then 'title' else 'text' end
        ) order by
            p.tier, p.is_agency,
            case when $16 = 'relevance' then p.rank end desc nulls last,
            case when $16 = 'salary' then p.sal end desc nulls last,
            case when $16 = 'popular' then p.popularity end desc nulls last,
            p.posted_at desc, p.id)
        from page p
        join public.jobs j on j.id = p.id
        left join page_stats ps on ps.job_id = p.id), '[]'::jsonb)
    )
  $q$
  into v_result
  using v_tsq, v_phrase, p_tags, p_city, p_remote, p_german, p_seniority,
        p_has_salary, p_min_salary, p_visa, p_relocation, p_direct_only,
        p_max_years, p_days, p_exclude_terms, p_sort, p_limit, p_offset,
        p_scope, p_hide_companies;

  return v_result;
end;
$function$;
