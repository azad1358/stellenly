// RSS feed for any search — job alerts without email or accounts.
// Deploy:  supabase functions deploy rss --no-verify-jwt
// URL:     https://<project>.supabase.co/functions/v1/rss?q=python&german=not_required,nice_to_have
// Accepts the same query parameters as the website URL.

const SITE_URL = Deno.env.get("SITE_URL") ?? "https://www.stellenly.com";
const SITE_NAME = Deno.env.get("SITE_NAME") ?? "Stellenly";
const BLUE_CARD: Record<string, number> = { standard: 50700, reduced: 45934 }; // keep in sync with web/config.js

const esc = (s: unknown) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" }[c]!));
const list = (v: string | null) => (v ? v.split(",").map((x) => x.trim()).filter(Boolean) : null);
const GERMAN: Record<string, string> = {
  not_required: "No German needed", nice_to_have: "German nice to have",
  required: "German required", not_mentioned: "German not mentioned",
};

Deno.serve(async (req) => {
  const p = new URL(req.url).searchParams;
  const body = {
    p_q: p.get("q"),
    p_tags: list(p.get("tags")),
    p_city: p.get("city"),
    p_remote: list(p.get("remote")),
    p_german: list(p.get("german")),
    p_seniority: list(p.get("seniority")),
    p_has_salary: p.get("salary") === "1",
    p_min_salary: BLUE_CARD[p.get("bluecard") ?? ""] ?? null,
    p_visa: p.get("visa") === "1",
    p_relocation: p.get("reloc") === "1",
    p_direct_only: p.get("direct") === "1",
    p_max_years: p.get("years") ? Number(p.get("years")) : null,
    p_days: p.get("days") ? Number(p.get("days")) : null,
    p_sort: "newest",
    p_limit: 50,
    p_offset: 0,
  };

  const url = Deno.env.get("SUPABASE_URL")!;
  const key = Deno.env.get("SUPABASE_ANON_KEY")!;
  const res = await fetch(`${url}/rest/v1/rpc/search_jobs`, {
    method: "POST",
    headers: { apikey: key, Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) return new Response("Search failed", { status: 502 });
  const data = await res.json();

  const searchUrl = `${SITE_URL}/?${p.toString()}`;
  const items = (data.items as Record<string, any>[]).map((j) => {
    const salary = j.salary_min ? ` · €${Math.round(j.salary_min / 1000)}k${j.salary_max && j.salary_max !== j.salary_min ? `–${Math.round(j.salary_max / 1000)}k` : ""}` : "";
    const desc = `${j.company} · ${j.city ?? "Germany"} · ${GERMAN[j.german_level] ?? ""}${salary}${j.visa_sponsorship ? " · Visa sponsorship" : ""}\n\n${(j.snippet ?? "").slice(0, 400)}`;
    return `<item>
  <title>${esc(`${j.title} — ${j.company}`)}</title>
  <link>${esc(j.url)}</link>
  <guid isPermaLink="false">${esc(j.id)}</guid>
  <pubDate>${new Date(j.first_seen_at ?? j.posted_at).toUTCString()}</pubDate>
  <description>${esc(desc)}</description>
</item>`;
  }).join("\n");

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>${esc(`${SITE_NAME}${p.get("q") ? ` — ${p.get("q")}` : ""}`)}</title>
  <link>${esc(searchUrl)}</link>
  <description>New English-friendly jobs in Germany matching your search</description>
  <language>en</language>
${items}
</channel>
</rss>`;

  return new Response(xml, {
    headers: {
      "Content-Type": "application/rss+xml; charset=utf-8",
      "Cache-Control": "public, max-age=1800",
      "Access-Control-Allow-Origin": "*",
    },
  });
});
