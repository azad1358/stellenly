// AI report for the Skill check page (web/skill-check.html).
// Deploy:  supabase functions deploy skill-report --no-verify-jwt   (secret: LLM_API_KEY, a Gemini key)
// POST {role, levels: {"Python": 7, ...}}  ->  {report, role, peers}
// The market data comes from the site's own skill-roles.json, never from the request; the candidate
// comparison from skill_peers(). A daily cap (REPORT_DAILY_MAX) keeps the free LLM quota for the job checks.

const SITE_URL = Deno.env.get("SITE_URL") ?? "https://www.stellenly.com";
const LLM_URL = Deno.env.get("LLM_API_URL") ?? "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions";
const MODELS = (Deno.env.get("REPORT_MODELS") ?? "gemini-flash-latest,gemini-flash-lite-latest").split(",");
const DAILY_MAX = Number(Deno.env.get("REPORT_DAILY_MAX") ?? 200);
const ORIGINS = [SITE_URL, "https://stellenly.com", "http://localhost:8765"];

type Skill = { n: string; s: number; r: number };
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

function prompt(role: Role, levels: Record<string, number>, peers: { n: number; skills: Record<string, { avg: number }> | null }) {
  const rows = role.skills.map((s) => {
    const peer = peers.skills?.[s.n]?.avg;
    return `- ${s.n}: asked in ${Math.round(s.s * 100)}% of postings, a must-have in ${Math.round(s.r * 100)}% of those;` +
      ` candidate ${levels[s.n] ?? "?"}/10${peer != null ? `; other candidates average ${peer}/10` : ""}`;
  }).join("\n");
  const peerLine = peers.skills
    ? `${peers.n} other candidates rated themselves for this role (anonymous self-ratings).`
    : `Fewer than 10 candidates rated this role so far: there is no candidate comparison yet; say so briefly.`;
  return `You are a friendly, honest career coach for internationals looking for English-speaking jobs in Germany.
A candidate is aiming for "${role.t}". From ${role.n} job postings of the last 90 days, these are the 10 skills asked most,
with the candidate's self-rating (1 = beginner, 10 = expert):
${rows}
${peerLine}

Self-ratings are rough. Many candidates underrate themselves and job ads are wish lists: hardly anyone meets every point.
Write a short, concrete report. Rules:
- Base every claim on the numbers above. Do not invent statistics, companies, salaries or URLs.
- Focus areas: at most 3 skills where demand is high and the rating is low (demand x gap). For each, explain why it
  matters for this role and how to improve: a small practice project and the kind of free resources to use
  (official docs, well-known free courses or books by name). No links.
- Strengths: skills the candidate is already good at relative to demand. Be specific, not flattering.
- Readiness: "apply_now" (most high-demand skills >= 6), "apply_while_learning" (a few gaps), or "build_first"
  (several must-haves <= 3). Encourage applying when close — applying while learning is normal.
- Interview: 3 topics to prepare for this role, based on the high-demand skills.
- A 4-week plan, one line per week.
- Plain English, short sentences, under 400 words in total.
Return JSON only:
{"headline": "one sentence", "readiness": "apply_now|apply_while_learning|build_first", "readiness_reason": "1-2 sentences",
 "strengths": [{"skill": "", "note": ""}], "focus": [{"skill": "", "why": "", "how": ""}],
 "peers": "1-2 sentences comparing with other candidates, or saying there is no comparison yet",
 "interview": ["", "", ""], "plan": ["Week 1: ...", "Week 2: ...", "Week 3: ...", "Week 4: ..."], "encouragement": "one sentence"}`;
}

async function llm(text: string) {
  for (const model of MODELS) {
    const res = await fetch(LLM_URL, {
      method: "POST",
      headers: { Authorization: `Bearer ${Deno.env.get("LLM_API_KEY")}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model, temperature: 0.4, response_format: { type: "json_object" },
                             messages: [{ role: "user", content: text }] }),
    });
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

  let body: { role?: unknown; levels?: unknown };
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
  const peers = await rpc("skill_peers", { p_role: role.t }, service);
  try {
    const report = await llm(prompt(role, levels, peers));
    if (!report) return fail(503, "The AI is busy right now. Please try again in a minute.");
    return new Response(JSON.stringify({ report, role, peers }), { headers });
  } catch (err) {
    console.error(err);
    return fail(502, "The report could not be generated. Please try again.");
  }
});
