// =====================================================================
// Site configuration — the only file you need to edit to go live.
// The anon key is PUBLIC by design (it can only read active jobs).
// NEVER put the service_role key here.
// Leave SUPABASE_URL empty to run the site with built-in demo data.
// =====================================================================
window.SITE_CONFIG = {
  SITE_NAME: "English Jobs Germany",
  OWNER_NOTE: "Built by Azad in Berlin — an international who went through this job search too. No accounts, no tracking, no CV uploads.",

  SUPABASE_URL: "https://udkkssqsrakxotevmkqq.supabase.co",          
  SUPABASE_ANON_KEY: "sb_publishable_ciUBl2xuafCYDimrJ6nRng_Ugoa1uEv",     // Settings → API → anon / publishable key

  // Support — the payment platform handles everything; the site only links out.
  KOFI_URL: "https://ko-fi.com/drazadabad",
  SUPPORTERS_URL: "https://ko-fi.com/your-name#supporters",

  // One quiet, clearly labelled sponsor slot (sold directly — no ad network,
  // no cookies). Set to null to hide it.
  SPONSOR: {
    label: "Your company here",
    text: "Reach thousands of internationals looking for English-speaking jobs in Germany.",
    url: "mailto:you@example.com?subject=Sponsoring",
  },

  // Transparency box. Update by hand once a month.
  COSTS: [
    { label: "Hosting (Cloudflare Pages)", eur: 0 },
    { label: "Database (Supabase free tier)", eur: 0 },
    { label: "Scheduled updates (GitHub Actions)", eur: 0 },
    { label: "Domain", eur: 1.5 },
  ],
  MONTHLY_GOAL_EUR: 20,
  RAISED_THIS_MONTH_EUR: 0,

  // EU Blue Card minimum gross yearly salary. Update every January
  // (official source: make-it-in-germany.com / Federal Foreign Office).
  BLUE_CARD: { year: 2026, standard: 50700, reduced: 45934 },

  // Ask for support once, after this many "Applied" clicks.
  NUDGE_AFTER_APPLIED: 5,
  PAGE_SIZE: 20,
};
