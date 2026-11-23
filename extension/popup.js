// Chrome/Edge expose `chrome`, Firefox exposes `browser` (both return promises in Manifest V3).
const ext = typeof browser !== "undefined" ? browser : chrome;

// config.js defines CONFIG. The fallback keeps the popup working even if config.js is missing.
const CFG = typeof CONFIG !== "undefined" ? CONFIG : { api: "http://127.0.0.1:8765", minAppVersion: "0.0.0" };
const API = CFG.api;
const $ = (id) => document.getElementById(id);
const PAGE_SITES = /(^|\.)(youtube\.com|youtu\.be|vimeo\.com|twitter\.com|x\.com|facebook\.com|instagram\.com|tiktok\.com|dailymotion\.com|twitch\.tv)$/;
const FINAL = ["done", "error", "unknown", "cancelled"];

let jobs = []; // [{id, title, status, percent, speed, eta, file, error, offline}]
let timer = null;
const els = new Map(); // id -> UI elements

// Extra styles for the cards, the job list and the quality controls
const extraStyle = document.createElement("style");
extraStyle.textContent = `
  .jtop { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .jtop .jname { flex: 1; margin: 0; }
  button.x { background: none; color: #888; padding: 0 4px; font-size: 15px; line-height: 1; }
  button.x:hover { color: #b91c1c; }
  .qrow { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 13px; }
  select { padding: 3px 6px; border-radius: 6px; border: 1px solid #ccc; }
  .ctitle { font-weight: 600; font-size: 14px; flex: 1; }
  .size { direction: ltr; unicode-bidi: isolate; font-size: 12px; color: #555; }
  .desc { font-size: 12px; color: #666; margin: 2px 0 6px; }
  .hint { font-weight: 600; } .hint-ok { color: #15803d; } .hint-warn { color: #b45309; }
  .crow { margin-top: 4px; }
  .crow select { flex: 1; }
  .note { font-size: 12px; color: #555; background: #f3f4f6; border-radius: 6px; padding: 6px 8px; margin-bottom: 8px; }`;
document.head.appendChild(extraStyle);

const QUALITY_OPTIONS = [
  ["best", "Best quality"], ["1080", "Up to 1080p"], ["720", "Up to 720p"],
  ["480", "Up to 480p"], ["360", "Up to 360p"], ["audio", "Audio only (MP3)"],
];
// ---------- Saved jobs (still visible when the popup is reopened) ----------
async function loadJobs() { jobs = (await ext.storage.local.get("jobs")).jobs || []; }
function saveJobs() { jobs = jobs.slice(0, 20); return ext.storage.local.set({ jobs }); }

// ---------- Helpers ----------
function fmtSize(n) {
  if (!n) return "";
  return n > 1e9 ? (n / 1e9).toFixed(2) + " GB" : (n / 1e6).toFixed(1) + " MB";
}
function fmtSpeed(b) { return b ? (b / 1e6).toFixed(1) + " MB/s" : ""; }
function fmtEta(s) {
  if (s == null) return "";
  const m = Math.floor(s / 60), r = Math.floor(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
}

// ---------- Progress bars ----------
function drawJob(j) {
  let e = els.get(j.id);
  if (!e) {
    const root = document.createElement("div");
    root.className = "job";
    root.innerHTML = `<div class="jtop"><div class="jname"></div><button class="x" title="Remove">✕</button></div><div class="bar"><div class="fill"></div></div><div class="jlabel"></div>`;
    e = { root, name: root.querySelector(".jname"), fill: root.querySelector(".fill"), label: root.querySelector(".jlabel") };
    root.querySelector(".x").onclick = () => removeJob(j.id);
    els.set(j.id, e);
    $("jobs").appendChild(root);
  }
  const known = typeof j.percent === "number";
  const final = FINAL.includes(j.status);
  e.name.textContent = j.title || "Video";
  e.fill.className = "fill" + (j.status === "done" ? " done" : final ? " err" : !known ? " indet" : "");
  e.fill.style.width = j.status === "done" ? "100%" : known ? j.percent + "%" : "";

  let text;
  if (j.offline && !final) text = "Could not reach the local app";
  else if (j.status === "queued") text = "Waiting...";
  else if (j.status === "downloading")
    text = known
      ? [`${Math.floor(j.percent)}%`, fmtSpeed(j.speed), j.eta != null ? fmtEta(j.eta) + " left" : ""].filter(Boolean).join(" · ")
      : `Downloading... ${fmtEta(j.started_at ? Date.now() / 1000 - j.started_at : null)} elapsed (progress is not available for this video)`;
  else if (j.status === "processing") text = "Merging audio and video...";
  else if (j.status === "done") text = "Done ✓ " + (j.file || j.title || "") + (j.height ? ` (${j.height}p)` : "") + (j.no_audio ? " ⚠ no audio track" : "");
  else if (j.status === "cancelled") text = "Cancelled";
  else if (j.status === "unknown") text = "Unknown job (the app was restarted)";
  else text = "Failed: " + (j.error || "unknown error");
  e.label.textContent = text;
  e.label.title = j.error_detail || "";  // technical details on hover
}

async function removeJob(id) {
  fetch(`${API}/jobs/${id}`, { method: "DELETE" }).catch(() => {}); // cancels the job if it is still running
  jobs = jobs.filter((x) => x.id !== id);
  await saveJobs();
  const e = els.get(id);
  if (e) { e.root.remove(); els.delete(id); }
  $("jobsBox").hidden = jobs.length === 0;
}

function drawAll() {
  $("jobs").replaceChildren();
  els.clear();
  jobs.forEach(drawJob);
  $("jobsBox").hidden = jobs.length === 0;
}

async function poll() {
  const active = jobs.filter((j) => !FINAL.includes(j.status));
  await Promise.all(active.map(async (j) => {
    try {
      const r = await (await fetch(`${API}/jobs/${j.id}`)).json();
      Object.assign(j, r, { offline: false });
    } catch { j.offline = true; }
    drawJob(j);
  }));
  await saveJobs();
  if (!jobs.some((j) => !FINAL.includes(j.status)) && timer) { clearInterval(timer); timer = null; }
}
function ensurePolling() { if (!timer) { timer = setInterval(poll, 1000); poll(); } }

$("clear").onclick = async () => {
  jobs = jobs.filter((j) => !FINAL.includes(j.status));
  await saveJobs();
  drawAll();
};

if (!$("clearAll")) {
  const b = document.createElement("button");
  b.id = "clearAll"; b.className = "link"; b.textContent = "Clear all";
  $("clear").after(" · ", b);
}
$("clearAll").onclick = async () => {
  jobs.forEach((j) => fetch(`${API}/jobs/${j.id}`, { method: "DELETE" }).catch(() => {}));
  jobs = [];
  await saveJobs();
  drawAll();
};

// ---------- Local app status ----------
function cmpVersion(a, b) {
  const pa = String(a || "0").split(".").map(Number), pb = String(b || "0").split(".").map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d) return d;
  }
  return 0;
}

const offlineStyle = document.createElement("style");
offlineStyle.textContent = `
  .offline { background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 10px; padding: 10px 12px; margin-bottom: 10px; }
  .offline b { display: block; margin-bottom: 4px; }
  .offline p { font-size: 12px; color: #555; margin: 4px 0 8px; }
  .offline .small { margin: 6px 0 0; }`;
document.head.appendChild(offlineStyle);

// Card that tells the user to install (or update) the helper app
function showInstallCard(title, text, btnText) {
  let box = $("offline");
  if (!box) {
    box = document.createElement("div");
    box.id = "offline";
    box.className = "offline";
    box.innerHTML = `<b></b><p class="t"></p><button></button><p class="small">Already installed? Start Media Catcher from the Start menu.</p>`;
    box.querySelector("button").onclick = () => ext.tabs.create({ url: ext.runtime.getURL("welcome.html") });
    $("warn").before(box);
  }
  box.querySelector("b").textContent = title;
  box.querySelector(".t").textContent = text;
  box.querySelector("button").textContent = btnText;
}

async function checkServer() {
  try {
    const h = await (await fetch(`${API}/health`)).json();
    $("status").textContent = "App connected" + (h.version ? " · v" + h.version : "");
    $("status").className = "ok";
    if (cmpVersion(h.version, CFG.minAppVersion) < 0) {
      showInstallCard("App version is outdated",
        `This extension needs app version ${CFG.minAppVersion} or newer (you have ${h.version || "an old one"}).`, "Update the app");
    }
    const warns = [];
    if (!h.ffmpeg) warns.push("ffmpeg not found: audio and video cannot be merged.");
    if (h.crypto === false) warns.push("pycryptodomex is not installed: progress may not show for encrypted course videos (pip install pycryptodomex).");
    if (h.deno === false) warns.push("Deno is not installed: YouTube downloads may fail with error 403.");
    if (warns.length) {
      $("warn").hidden = false;
      $("warn").textContent = warns.join("\n");
    }
  } catch {
    $("status").textContent = "App is not running";
    $("status").className = "bad";
    showInstallCard("The helper app is not running",
      "The extension detects the video, but the download is done by a small app on your computer. Install it once.", "Install the app");
  }
}

// ---------- Sending ----------
// Label that tells similar downloads apart in the list (video or audio, which quality)
function qualityTag(q) {
  if (q === "audio") return " · audio only";
  if (/^\d+$/.test(q || "")) return ` · up to ${q}p`;
  return "";
}

async function send(item, serverTitle, displayTitle, btn, msg, quality) {
  btn.disabled = true;
  msg.className = "msg";
  msg.textContent = "Sending...";
  try {
    const r = await fetch(`${API}/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: item.url, headers: item.headers || {}, title: serverTitle, page_url: item.frameUrl || "", quality }),
    });
    if (!r.ok) throw new Error(r.status);
    const { id } = await r.json();
    jobs.unshift({ id, title: displayTitle + qualityTag(quality), status: "queued", percent: null });
    await saveJobs();
    drawAll();
    ensurePolling();
    msg.textContent = "Added to downloads";
  } catch {
    msg.textContent = "Could not reach the local app";
    msg.className = "msg bad";
  }
  setTimeout(() => (btn.disabled = false), 1500);
}

// ---------- Quality guessed from the URL ----------
const KNOWN_HEIGHTS = [144, 240, 360, 480, 540, 576, 720, 1080, 1440, 2160];

// e.g. /360p/index.webm, video_720.mp4 or ?quality=1080
function detectQuality(url) {
  let u;
  try { u = new URL(url); } catch { return null; }
  const path = u.pathname.toLowerCase();
  let m = path.match(/(?:^|[\/_\-.])(\d{3,4})p(?![a-z0-9])/);
  if (m && KNOWN_HEIGHTS.includes(+m[1])) return +m[1];
  m = path.match(/(?:^|[\/_\-])(\d{3,4})(?=[\/_\-.]|$)/);
  if (m && KNOWN_HEIGHTS.includes(+m[1])) return +m[1];
  for (const k of ["height", "quality", "res", "resolution", "h"]) {
    const v = parseInt(u.searchParams.get(k) || "", 10);
    if (KNOWN_HEIGHTS.includes(v)) return v;
  }
  return null;
}

const KIND_INFO = {
  page: { name: "Page link", desc: "Extracts the video and audio from the page itself." },
  file: { name: "Video file", desc: "A ready-made file with a fixed quality." },
  hls: { name: "HLS stream", desc: "A stream that is assembled into one file." },
  dash: { name: "DASH stream", desc: "A stream that is assembled into one file." },
};

function shortUrl(url) {
  try {
    const u = new URL(url);
    return `${u.hostname} › ${u.pathname.split("/").filter(Boolean).pop() || ""}`;
  } catch { return url; }
}

// quality != null  =>  fixed quality (a single file), so choosing another quality is meaningless:
// the only options are the file as it is, or audio only.
function makeCard({ kind, quality, size, url, hint, hintWarn, savedQuality, onSend }) {
  const info = KIND_INFO[kind] || { name: kind.toUpperCase(), desc: "" };
  const fixed = quality != null;
  const el = document.createElement("div");
  el.className = "item";
  el.innerHTML = `<div class="row"><span class="ctitle"></span><span class="size"></span></div>
                  <div class="desc"></div>
                  <div class="row crow"><select class="csel"></select><button>Download</button></div>
                  <div class="url"></div><div class="msg"></div>`;
  el.querySelector(".ctitle").textContent = info.name + (fixed ? ` · ${quality}p` : "");
  el.querySelector(".size").textContent = size || "";
  const desc = el.querySelector(".desc");
  desc.textContent = info.desc + " ";
  if (hint) {
    const h = document.createElement("span");
    h.className = "hint " + (hintWarn ? "hint-warn" : "hint-ok");
    h.textContent = hint;
    desc.appendChild(h);
  }
  const urlEl = el.querySelector(".url");
  urlEl.textContent = shortUrl(url);
  urlEl.title = url;

  const sel = el.querySelector(".csel");
  const opts = fixed
    ? [["best", `This quality (${quality}p)`], ["audio", "Audio only (MP3)"]]
    : QUALITY_OPTIONS;
  sel.innerHTML = opts.map(([v, t]) => `<option value="${v}">${t}</option>`).join("");
  if (!fixed) {
    if (opts.some(([v]) => v === savedQuality)) sel.value = savedQuality;
    sel.onchange = () => ext.storage.local.set({ quality: sel.value });
  }

  const btn = el.querySelector("button"), msg = el.querySelector(".msg");
  btn.onclick = () => onSend(btn, msg, sel.value);
  return el;
}

// ---------- Start ----------
(async () => {
  checkServer();
  await loadJobs();
  drawAll();
  if (jobs.some((j) => !FINAL.includes(j.status))) ensurePolling();
  const savedQuality = (await ext.storage.local.get("quality")).quality;

  const [tab] = await ext.tabs.query({ active: true, currentWindow: true });
  let host = "";
  try { host = new URL(tab.url).hostname; } catch {}
  const pageTitle = tab.title || host || "video";

  // Card for the page URL itself (yt-dlp extracts the video and audio from it)
  if (/^https?:/.test(tab.url || "")) {
    const recommended = PAGE_SITES.test(host);
    $("list").appendChild(makeCard({
      kind: "page", quality: null, url: tab.url, savedQuality,
      hint: recommended ? "Recommended for this site" : "yt-dlp may not support it",
      hintWarn: !recommended,
      onSend: (btn, msg, q) => send({ url: tab.url, headers: {} }, "", pageTitle, btn, msg, q),
    }));
  }

  // Detected media: merge duplicates (same file, new signature) and sort the highest quality first
  const k = `tab:${tab.id}`;
  const list = (await ext.storage.session.get(k))[k] || [];
  const byKey = new Map();
  for (const item of list) {
    const q = detectQuality(item.url);
    let key = item.url;
    if (q) { try { const u = new URL(item.url); key = `${u.origin}${u.pathname}|${q}`; } catch {} }
    const prev = byKey.get(key);
    if (!prev || item.time > prev.item.time) byKey.set(key, { item, q });
  }
  const entries = [...byKey.values()].sort((a, b) => (b.q || 0) - (a.q || 0));
  $("empty").hidden = entries.length > 0;

  if (entries.length) {
    const h = document.createElement("h2");
    h.textContent = "Files detected on this page";
    const note = document.createElement("div");
    note.className = "note";
    note.textContent = "The extension caught these files while the video was playing, one card per quality. For a quality that is not listed: change it in the video player's settings, then reopen this popup.";
    $("list").append(h, note);
  }
  for (const { item, q } of entries) {
    // Add the quality to the name so one quality never replaces another
    const title = q ? `${pageTitle} - ${q}p` : pageTitle;
    $("list").appendChild(makeCard({
      kind: item.kind, quality: q, size: fmtSize(item.size), url: item.url, savedQuality,
      onSend: (btn, msg, qual) => send(item, title, title, btn, msg, qual),
    }));
  }
})();
