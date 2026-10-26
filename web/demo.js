// Demo backend: used only when SUPABASE_URL is empty, so you can preview the
// site before connecting the database. Mirrors search_jobs()/facets()/site_stats().
(function () {
  const now = Date.now();
  const ago = (h) => new Date(now - h * 3600e3).toISOString();
  const J = (o) => Object.assign({
    location: o.city, job_types: ["full time"], tags: [], is_agency: false, relocation: false,
    visa_sponsorship: false, salary_min: null, salary_max: null, years_experience: null,
    repost_count: 0, first_seen_at: o.posted_at,
  }, o);

  const JOBS = [
    J({ id: "d1", title: "Senior Machine Learning Engineer (LLMs)", company: "Nordlicht AI", city: "Berlin",
      remote_type: "hybrid", german_level: "not_required", seniority: "senior", years_experience: 5,
      salary_min: 85000, salary_max: 105000, visa_sponsorship: true, relocation: true, posted_at: ago(3),
      tags: ["ai-ml", "python", "senior", "visa-sponsorship", "relocation", "no-german"],
      url: "https://example.com/jobs/1",
      snippet: "We build document AI for European insurers. You'll own our LLM extraction pipeline end to end.\nNo German required — our team of 14 nationalities works in English.\n5+ years of experience with Python and production ML." }),
    J({ id: "d2", title: "Junior Data Analyst", company: "Kiezkasse", city: "Berlin",
      remote_type: "remote_de", german_level: "nice_to_have", seniority: "junior", years_experience: 1,
      salary_min: 48000, salary_max: 55000, posted_at: ago(20), tags: ["data", "junior", "remote"],
      url: "https://example.com/jobs/2",
      snippet: "Help our finance team make sense of payments data with SQL and Python.\nGerman is a plus, but English is our working language." }),
    J({ id: "d3", title: "Product Manager — Payments", company: "Elbe Fintech", city: "Hamburg",
      remote_type: "hybrid", german_level: "required", seniority: "mid", years_experience: 3,
      posted_at: ago(30), tags: ["product"], url: "https://example.com/jobs/3",
      snippet: "You speak fluent German and English and work closely with our banking partners." }),
    J({ id: "d4", title: "Backend Engineer (Go)", company: "Isar Robotics", city: "Munich",
      remote_type: "onsite", german_level: "not_mentioned", seniority: "unspecified",
      salary_min: 70000, salary_max: 90000, posted_at: ago(50), tags: ["backend", "go", "cloud"],
      url: "https://example.com/jobs/4",
      snippet: "Write the services that coordinate 300 warehouse robots. Kubernetes, Postgres, gRPC." }),
    J({ id: "d5", title: "Werkstudent Marketing (m/w/d)", company: "Rheinwerk Studios", city: "Cologne",
      remote_type: "hybrid", german_level: "nice_to_have", seniority: "intern", job_types: ["Werkstudent"],
      salary_min: null, posted_at: ago(70), tags: ["marketing", "intern"], url: "https://example.com/jobs/5",
      snippet: "20 hours per week, flexible around your studies. Basic German is appreciated." }),
    J({ id: "d6", title: "Senior Account Executive DACH", company: "Talentbridge Recruiting", city: "Frankfurt",
      remote_type: "onsite", german_level: "required", seniority: "senior", is_agency: true, posted_at: ago(90),
      salary_min: 60000, salary_max: 80000, tags: ["sales", "senior"], url: "https://example.com/jobs/6",
      snippet: "On behalf of our client, a SaaS scale-up, we are looking for an AE. Business-fluent German required." }),
    J({ id: "d7", title: "Frontend Developer (React/TypeScript)", company: "Spree Health", city: "Berlin",
      remote_type: "remote_eu", german_level: "not_required", seniority: "mid", years_experience: 3,
      salary_min: 62000, salary_max: 78000, visa_sponsorship: true, posted_at: ago(5),
      job_types: ["unbefristeter arbeitsvertrag"], tags: ["frontend", "react", "typescript", "remote", "visa-sponsorship", "no-german"],
      url: "https://example.com/jobs/7", repost_count: 2,
      snippet: "Remote within the EU. Build the patient app used by 400k people.\nWe sponsor visas and help with your Blue Card." }),
    J({ id: "d8", title: "DevOps Engineer", company: "Neckar Cloudworks", city: "Stuttgart",
      remote_type: "hybrid", german_level: "nice_to_have", seniority: "mid", years_experience: 4,
      salary_min: 65000, salary_max: 82000, relocation: true, posted_at: ago(120), tags: ["devops", "cloud", "relocation"],
      url: "https://example.com/jobs/8",
      snippet: "Terraform, AWS, on-call once a month. Relocation package for candidates moving to Stuttgart." }),
    J({ id: "d9", title: "Customer Success Manager (English)", company: "Leipzig Logistics", city: "Leipzig",
      remote_type: "onsite", german_level: "not_required", seniority: "junior", years_experience: 1,
      salary_min: 42000, salary_max: 48000, posted_at: ago(200), tags: ["customer-support", "junior", "no-german"],
      url: "https://example.com/jobs/9",
      snippet: "Support our international shipping customers in English. Teilzeit possible." }),
    J({ id: "d10", title: "Staff Data Engineer", company: "Nordlicht AI", city: "Berlin",
      remote_type: "remote_de", german_level: "not_mentioned", seniority: "lead", years_experience: 8,
      salary_min: 100000, salary_max: 120000, visa_sponsorship: true, posted_at: ago(260),
      tags: ["data", "python", "remote", "visa-sponsorship"], url: "https://example.com/jobs/10",
      snippet: "Design our lakehouse and data contracts. Spark, dbt, Kafka." }),
  ];

  const has = (a) => Array.isArray(a) && a.length > 0;

  function search(p) {
    const q = (p.p_q || "").toLowerCase().trim();
    let r = JOBS.filter((j) => {
      const blob = `${j.title} ${j.company} ${j.tags.join(" ")} ${j.snippet}`.toLowerCase();
      if (q && !q.split(/\s+/).every((w) => blob.includes(w))) return false;
      if (has(p.p_tags) && !p.p_tags.every((t) => j.tags.includes(t))) return false;
      if (p.p_city && j.city !== p.p_city) return false;
      if (has(p.p_remote) && !p.p_remote.includes(j.remote_type)) return false;
      if (has(p.p_german) && !p.p_german.includes(j.german_level)) return false;
      if (has(p.p_seniority) && !p.p_seniority.includes(j.seniority)) return false;
      if (p.p_has_salary && j.salary_min == null) return false;
      if (p.p_min_salary && (j.salary_max ?? j.salary_min ?? -1) < p.p_min_salary) return false;
      if (p.p_visa && !j.visa_sponsorship) return false;
      if (p.p_relocation && !j.relocation) return false;
      if (p.p_direct_only && j.is_agency) return false;
      if (p.p_max_years != null && j.years_experience != null && j.years_experience > p.p_max_years) return false;
      if (p.p_days && new Date(j.posted_at) < new Date(now - p.p_days * 864e5)) return false;
      if (has(p.p_exclude_terms) && p.p_exclude_terms.some((t) => t && j.title.toLowerCase().includes(t.toLowerCase()))) return false;
      if (has(p.p_hide_companies) && p.p_hide_companies.includes(j.company)) return false;
      return true;
    });
    if (p.p_sort === "salary") r.sort((a, b) => (b.salary_max ?? b.salary_min ?? -1) - (a.salary_max ?? a.salary_min ?? -1));
    else r.sort((a, b) => new Date(b.posted_at) - new Date(a.posted_at));
    const off = p.p_offset || 0, lim = p.p_limit || 20;
    return { total: r.length, items: r.slice(off, off + lim) };
  }

  function count(key, flat) {
    const m = new Map();
    JOBS.forEach((j) => (flat ? j[key] : [j[key]]).forEach((v) => m.set(v, (m.get(v) || 0) + 1)));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }

  window.DemoBackend = {
    search_jobs: (p) => search(p),
    facets: () => ({
      tags: count("tags", true).slice(0, 30).map(([tag, c]) => ({ tag, count: c })),
      cities: count("city", false).map(([city, c]) => ({ city, count: c })),
    }),
    site_stats: () => ({ active: JOBS.length, added_today: JOBS.filter((j) => now - new Date(j.first_seen_at) < 864e5).length, hired: 12 }),
    record_hire: () => null,
  };
})();
