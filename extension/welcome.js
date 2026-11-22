const API = CONFIG.api;
const $ = (id) => document.getElementById(id);
const isWindows = /Windows/i.test(navigator.userAgent);
const placeholder = !CONFIG.installerUrl || CONFIG.installerUrl.includes("YOUR_GITHUB_NAME");

function cmpVersion(a, b) {
  const pa = String(a || "0").split(".").map(Number), pb = String(b || "0").split(".").map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d) return d;
  }
  return 0;
}

$("nonwin").hidden = isWindows;
$("devwarn").hidden = !placeholder;
$("download").disabled = placeholder;
$("download").onclick = () => {
  chrome.tabs.create({ url: CONFIG.installerUrl });
  $("dlnote").hidden = false;
};

async function check() {
  let h = null;
  try { h = await (await fetch(`${API}/health`)).json(); } catch {}
  const box = $("live"), text = $("liveText");
  if (!h) {
    box.className = "live wait";
    text.textContent = "Waiting for the app... (checks automatically every 2 seconds)";
  } else if (cmpVersion(h.version, CONFIG.minAppVersion) < 0) {
    box.className = "live old";
    text.textContent = `The app is running, but its version (${h.version || "old"}) is older than the required one (${CONFIG.minAppVersion}). Install the latest version.`;
  } else {
    box.className = "live ok";
    text.textContent = `✓ The app is running (v${h.version}). You can start now.`;
  }
}
setInterval(check, 2000);
check();
