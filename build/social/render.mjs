// Renders every slide-*.html in a folder to slide-*.jpg (1080x1350, the Instagram portrait size) with headless
// Chrome / Edge over the DevTools protocol. Used by build/social_posts.py; no npm packages needed (Node 22+).
//   node build/social/render.mjs <folder>        CHROME=/path/to/chrome overrides the browser
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const dir = path.resolve(process.argv[2]);
const browser = process.env.CHROME || ["/usr/bin/google-chrome", "/usr/bin/chromium-browser", "/usr/bin/chromium",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Google/Chrome/Application/chrome.exe"]
  .find((p) => fs.existsSync(p));
if (!browser) throw new Error("no Chrome / Edge found: set CHROME");
const port = 9400 + Math.floor(Math.random() * 400);
const proc = spawn(browser, ["--headless=new", "--disable-gpu", "--no-sandbox", "--allow-file-access-from-files",
  `--remote-debugging-port=${port}`, `--user-data-dir=${fs.mkdtempSync(path.join(os.tmpdir(), "social-"))}`, "about:blank"]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let target;
for (let i = 0; i < 40 && !target; i++) {
  await sleep(250);
  try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === "page"); } catch { /* starting */ }
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0;
const pending = new Map();
ws.addEventListener("message", (m) => { const d = JSON.parse(m.data); if (pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } });
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1080, height: 1350, deviceScaleFactor: 1, mobile: false });
for (const file of fs.readdirSync(dir).filter((f) => /^slide-\d+\.html$/.test(f)).sort()) {
  await send("Page.navigate", { url: "file:///" + path.join(dir, file).split(path.sep).join("/") });
  await sleep(1500); // fonts and logos
  const shot = await send("Page.captureScreenshot", { format: "jpeg", quality: 90, clip: { x: 0, y: 0, width: 1080, height: 1350, scale: 1 } });
  fs.writeFileSync(path.join(dir, file.replace(".html", ".jpg")), Buffer.from(shot.result.data, "base64"));
}
proc.kill();
process.exit(0);
