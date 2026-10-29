// =====================================================================
// Site configuration — the only file you need to edit to go live.
// The anon key is PUBLIC by design (it can only read active jobs).
// NEVER put the service_role key here.
// Leave SUPABASE_URL empty to run the site with built-in demo data.
// =====================================================================
window.SITE_CONFIG = {
  SITE_NAME: "Stellenly",
  OWNER_NAME: "Azad",
  OWNER_URL: "https://azadabad.com",
  OWNER_NOTE: "in Berlin — an international who went through this job search too.",

  SUPABASE_URL: "https://udkkssqsrakxotevmkqq.supabase.co",          
  SUPABASE_ANON_KEY: "sb_publishable_ciUBl2xuafCYDimrJ6nRng_Ugoa1uEv",     // Settings → API → anon / publishable key

  // Support — the payment platform handles everything; the site only links out.
  KOFI_URL: "https://ko-fi.com/drazadabad",
  SUPPORTERS_URL: "https://ko-fi.com/your-name#supporters",

  // Clearly labelled sponsor slot (sold directly — no ad network, no cookies). One entry is
  // picked at random on each visit. Only list real sponsors or real partner programmes:
  // kind "sponsor" = paid placement, "partner" = affiliate link, "offer" = ad space for sale.
  SPONSORS: [
    {
      kind: "offer",
      label: "Your company here",
      text: "Reach thousands of internationals looking for English-speaking jobs in Germany.",
      url: "mailto:abad.623@gmail.com?subject=Advertising%20on%20Stellenly",
    },
  ],

  // Running costs, shown honestly. "now" = what we pay today (free tiers where possible),
  // "grow" = what it costs once traffic outgrows the free tiers. Update by hand.
  COSTS: [
    { label: "Domain (stellenly.com)", now: 1.5, grow: 1.5 },
    { label: "Job database (Supabase)", now: 0, grow: 25, note: "free tier today, Pro plan as we grow" },
    { label: "AI job checks (Gemini)", now: 0, grow: 15, note: "free tier today, rate-limited" },
    { label: "Email job alerts", now: 0, grow: 10, note: "planned" },
    { label: "Hosting & updates (GitHub)", now: 0, grow: 0 },
  ],
  HOURS_PER_MONTH: 25,            // unpaid time for development, data checks and guides
  MONTHLY_GOAL_EUR: 50,
  RAISED_THIS_MONTH_EUR: 0,

  // EU Blue Card minimum gross yearly salary. Update every January
  // (official source: make-it-in-germany.com / Federal Foreign Office).
  BLUE_CARD: { year: 2026, standard: 50700, reduced: 45934 },

  // Ask for support once, after this many "Applied" clicks.
  NUDGE_AFTER_APPLIED: 5,
  PAGE_SIZE: 20,
};
