// AI report for the Skill check page (web/skill-check.html).
// Deploy:  supabase functions deploy skill-report --no-verify-jwt   (secret: LLM_API_KEY, a Gemini key)
// POST {role, levels: {"Python": 7, ...}, client: "<random browser id>"}  ->  {report, role, peers}
// The market data comes from the site's own skill-roles.json, never from the request; the candidate
// comparison from skill_peers(). A daily cap (REPORT_DAILY_MAX) keeps the free LLM quota for the job checks.
// The prompt text is in prompts.md at the repo root; prompts.json is made from it before deploying / serving:
//   python ingest/prompts.py supabase/functions/skill-report/prompts.json
import PROMPTS from "./prompts.json" with { type: "json" };

const SITE_URL = Deno.env.get("SITE_URL") ?? "https://www.stellenly.com";
const LLM_URL = Deno.env.get("LLM_API_URL") ?? "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions";
// Lite first: ~15 s for a report on the free tier; the bigger model is often overloaded or out of daily quota.
const MODELS = (Deno.env.get("REPORT_MODELS") ?? "gemini-flash-lite-latest,gemini-flash-latest").split(",");
const DAILY_MAX = Number(Deno.env.get("REPORT_DAILY_MAX") ?? 200);
const ORIGINS = [SITE_URL, "https://stellenly.com", "http://localhost:8765"];

type Skill = { n: string; s: number; r: number; p: number };
type Peers = { n: number; skills: Record<string, { avg: number; pct: number }> | null };
type Role = { t: string; n: number; skills: Skill[] };

const cors = (req: Request) => ({
  "Access-Control-Allow-Origin": ORIGINS.includes(req.headers.get("Origin") ?? "") ? req.headers.get("Origin")! : SITE_URL,
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "content-type",
  "Vary": "Origin",
});

async function rpc(name: string, body: unknown, key: string) {
  const res = await fetch(`${Deno.env.get("SUPABASE_URL")}/rest/v1/rpc/${name}`, {
    method: "POST",
    headers: { apikey: key, Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${name}: ${res.status}`);
  return res.json();
}

// One pass, like ingest/prompts.py: {key} -> values[key]; other braces (the JSON example) stay.
const fill = (name: string, values: Record<string, string | number>) =>
  (PROMPTS as Record<string, string>)[name].replace(/\{(\w+)\}/g, (all, k) => (k in values ? String(values[k]) : all));

function prompt(role: Role, levels: Record<string, number>, peers: Peers) {
  const rows = role.skills.map((s) => {
    const peer = peers.skills?.[s.n];
    return `- ${s.n}: priority ${s.p}/100 (asked in ${Math.round(s.s * 100)}% of postings, a must-have in ${Math.round(s.r * 100)}% of those);` +
      ` candidate ${levels[s.n] ?? "?"}/10${peer ? `; other candidates average ${peer.avg}/10, the candidate rated higher than ${peer.pct}% of them` : ""}`;
  }).join("\n");
  const peerLine = peers.skills ? fill("skill_report_peers", { n: peers.n }) : fill("skill_report_no_peers", {});
  return fill("skill_report", { role: role.t, n_jobs: role.n, rows, peers: peerLine });
}

async function llm(text: string) {
  for (const model of MODELS) {
    let res: Response;
    try {
      res = await fetch(LLM_URL, {
        method: "POST",
        headers: { Authorization: `Bearer ${Deno.env.get("LLM_API_KEY")}`, "Content-Type": "application/json" },
        body: JSON.stringify({ model, temperature: 0.4, response_format: { type: "json_object" },
                               messages: [{ role: "user", content: text }] }),
        signal: AbortSignal.timeout(25_000),  // an overloaded model can hang: move on to the next one
      });
    } catch { continue; }
    if (res.status === 429 || res.status === 404 || res.status >= 500) continue;  // quota / model gone: try the next one
    if (!res.ok) throw new Error(`LLM ${res.status}: ${(await res.text()).slice(0, 200)}`);
    const content = (await res.json()).choices?.[0]?.message?.content ?? "";
    return JSON.parse(content.replace(/^```(json)?|```$/g, "").trim());
  }
  return null;
}

Deno.serve(async (req) => {
  const headers = { ...cors(req), "Content-Type": "application/json" };
  if (req.method === "OPTIONS") return new Response(null, { headers });
  const fail = (status: number, error: string) => new Response(JSON.stringify({ error }), { status, headers });
  if (req.method !== "POST") return fail(405, "POST only");

  let body: { role?: unknown; levels?: unknown; client?: unknown };
  try { body = await req.json(); } catch { return fail(400, "Invalid JSON"); }
  const roles: Role[] = (await (await fetch(`${SITE_URL}/skill-roles.json`)).json()).roles;
  const role = roles.find((r) => r.t === body.role);
  if (!role) return fail(400, "Unknown role");
  const levels: Record<string, number> = {};
  for (const s of role.skills) {
    const v = Number((body.levels as Record<string, unknown> | undefined)?.[s.n]);
    if (Number.isInteger(v) && v >= 1 && v <= 10) levels[s.n] = v;
  }
  if (Object.keys(levels).length < role.skills.length) return fail(400, "Rate every skill from 1 to 10");

  const service = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  if (!(await rpc("take_report_quota", { p_max: DAILY_MAX }, service))) {
    return fail(429, "Today's free AI reports are used up. Your ratings are saved — please try again tomorrow.");
  }
  const client = typeof body.client === "string" && /^[0-9a-f-]{36}$/i.test(body.client) ? body.client : null;
  const peers: Peers = await rpc("skill_peers", { p_role: role.t, p_client: client, p_levels: levels }, service);
  try {
    const report = await llm(prompt(role, levels, peers));
    if (!report) return fail(503, "The AI is busy right now. Please try again in a minute.");
    return new Response(JSON.stringify({ report, role, peers }), { headers });
  } catch (err) {
    console.error(err);
    return fail(502, "The report could not be generated. Please try again.");
  }
});
