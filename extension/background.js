// Catches media requests for every tab and stores them together with the headers needed to download them.
const KEEP = ["referer", "origin", "cookie", "user-agent", "authorization"];
const SKIP_EXT = /\.(ts|m4s|aac|vtt|webvtt|jpe?g|png|gif|webp|js|css|woff2?)$/;
const MIN_FILE_SIZE = 1024 * 1024; // ignore small mp4 files (< 1 MB)

const pending = new Map(); // requestId -> headers
let chain = Promise.resolve(); // serializes writes to storage

const key = (tabId) => `tab:${tabId}`;

// 1) Keep each request's headers for a moment (Cookie is only visible with extraHeaders)
chrome.webRequest.onSendHeaders.addListener(
  (d) => {
    if (d.tabId < 0) return;
    const h = {};
    for (const { name, value } of d.requestHeaders || []) {
      if (KEEP.includes(name.toLowerCase())) h[name] = value;
    }
    pending.set(d.requestId, h);
    if (pending.size > 300) pending.delete(pending.keys().next().value);
  },
  { urls: ["<all_urls>"] },
  ["requestHeaders", "extraHeaders"]
);

// 2) When the response arrives, decide whether it is media
chrome.webRequest.onHeadersReceived.addListener(
  (d) => {
    const headers = pending.get(d.requestId) || {};
    pending.delete(d.requestId);
    if (d.tabId < 0 || d.statusCode >= 400) return;

    const res = {};
    for (const { name, value } of d.responseHeaders || []) res[name.toLowerCase()] = value || "";
    const kind = detect(d.url, res);
    if (!kind) return;

    const frameUrl = d.documentUrl || d.initiator || "";
    if (!Object.keys(headers).some((k) => k.toLowerCase() === "referer") && frameUrl) {
      headers["Referer"] = frameUrl;
    }
    addItem(d.tabId, { url: d.url, kind, size: totalSize(res), headers, frameUrl, time: Date.now() });
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders", "extraHeaders"]
);

function totalSize(res) {
  const m = /\/(\d+)$/.exec(res["content-range"] || "");
  if (m) return Number(m[1]);
  return Number(res["content-length"] || 0);
}

function detect(url, res) {
  let path;
  try { path = new URL(url).pathname.toLowerCase(); } catch { return null; }
  // YouTube (googlevideo) serves audio and video as separate streams, so downloading one directly gives a silent video.
  // Those sites are downloaded through the page URL instead (the "This page" card in the popup).
  if (new URL(url).hostname.endsWith("googlevideo.com")) return null;
  const ct = (res["content-type"] || "").toLowerCase();
  if (SKIP_EXT.test(path) || ct.includes("mp2t")) return null;
  if (path.endsWith(".m3u8") || ct.includes("mpegurl")) return "hls";
  if (path.endsWith(".mpd") || ct.includes("dash+xml")) return "dash";
  if (ct.startsWith("video/") || /\.(mp4|webm|mkv)$/.test(path)) {
    const size = totalSize(res);
    return size === 0 || size >= MIN_FILE_SIZE ? "file" : null;
  }
  return null;
}

function addItem(tabId, item) {
  chain = chain.then(async () => {
    const k = key(tabId);
    const data = await chrome.storage.session.get(k);
    const list = data[k] || [];
    if (list.some((x) => x.url === item.url)) return;
    list.unshift(item);
    await chrome.storage.session.set({ [k]: list.slice(0, 30) });
    chrome.action.setBadgeBackgroundColor({ tabId, color: "#2563eb" });
    chrome.action.setBadgeText({ tabId, text: String(Math.min(list.length, 99)) });
  }).catch(console.error);
}

// 3) Clean up on navigation or when the tab closes
chrome.tabs.onUpdated.addListener((tabId, info) => {
  if (info.url) {
    chain = chain.then(() => chrome.storage.session.remove(key(tabId)));
    chrome.action.setBadgeText({ tabId, text: "" });
  }
});
chrome.tabs.onRemoved.addListener((tabId) => {
  chain = chain.then(() => chrome.storage.session.remove(key(tabId)));
});

// On first install: a welcome page explains how to install the helper app and checks for it automatically
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.tabs.create({ url: chrome.runtime.getURL("welcome.html") });
  }
});
