"""Mobile scanner page served at GET /p/<token>.

Self-contained HTML+JS — no CDN/network dependencies (works offline on LAN).
Uses the native BarcodeDetector API where available; otherwise shows the
manual-paste fallback. Every relay POST is signed with the pairing token
header plus a fresh nonce + timestamp (server-side replay protection).
"""

SCANNER_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>TON Wallet — mobile companion</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; font-family: -apple-system, "Segoe UI", sans-serif; }
  body { margin: 0; background: #10161E; color: #E7ECEF; min-height: 100vh;
         display: flex; flex-direction: column; align-items: center; padding: 20px; }
  h1 { font-size: 20px; margin: 8px 0 4px; }
  .sub { color: #9AA6B2; font-size: 13px; margin-bottom: 16px; text-align: center; }
  .card { background: #1D2633; border: 1px solid #2E3A48; border-radius: 14px;
          padding: 16px; width: 100%; max-width: 480px; margin-bottom: 14px; }
  video { width: 100%; border-radius: 10px; background: #000; aspect-ratio: 4/3; }
  textarea, input { width: 100%; background: #10161E; border: 1px solid #2E3A48;
          border-radius: 8px; color: #E7ECEF; padding: 10px; font-size: 14px;
          font-family: monospace; resize: vertical; }
  button { background: #45AEF5; color: #0b1016; font-weight: 700; border: 0;
          border-radius: 10px; padding: 12px 16px; font-size: 15px; width: 100%;
          margin-top: 10px; cursor: pointer; }
  button.ghost { background: #232D3C; color: #E7ECEF; }
  button:disabled { opacity: .5; }
  #status { font-size: 14px; text-align: center; min-height: 20px; }
  .ok { color: #39D98A; } .err { color: #E74C3C; } .dim { color: #9AA6B2; }
  .hidden { display: none; }
</style>
</head>
<body>
  <h1>Mobile companion</h1>
  <div class="sub">Scan a TonConnect or ton:// QR code to relay it to your
    desktop wallet for approval. Nothing is sent or signed here.</div>

  <div class="card">
    <video id="video" playsinline muted></video>
    <div id="cameraStatus" class="dim" style="margin-top:8px">Requesting camera…</div>
    <button id="stopBtn" class="ghost hidden">Stop camera</button>
  </div>

  <div class="card">
    <div class="dim" style="margin-bottom:6px">Or paste the link manually:</div>
    <textarea id="manual" rows="3" placeholder="tc://…  |  https://…?v=2&id=…  |  ton://transfer/…"></textarea>
    <button id="sendBtn">Send to desktop</button>
    <button id="demoBtn" class="ghost hidden">Simulate a demo scan</button>
  </div>

  <div id="status"></div>

<script>
const TOKEN = "__TOKEN__";
const DEMO = __DEMO__;
const statusEl = document.getElementById("status");
const video = document.getElementById("video");
const cameraStatus = document.getElementById("cameraStatus");
const stopBtn = document.getElementById("stopBtn");
const demoBtn = document.getElementById("demoBtn");
let stream = null, scanning = false;

function setStatus(msg, cls) { statusEl.textContent = msg; statusEl.className = cls || "dim"; }
function nonce() {
  const b = crypto.getRandomValues(new Uint8Array(24));
  return btoa(String.fromCharCode(...b)).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}
async function relay(payload) {
  setStatus("Sending to desktop…");
  try {
    const r = await fetch("/api/relay", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-Pairing-Token": TOKEN},
      body: JSON.stringify({payload, nonce: nonce(), ts: Math.floor(Date.now() / 1000)})
    });
    const data = await r.json();
    if (!r.ok) { setStatus("Rejected: " + (data.error || r.status), "err"); return; }
    setStatus("Relayed — waiting for desktop approval…");
    pollStatus(data.id);
  } catch (e) { setStatus("Network error: " + e, "err"); }
}
async function pollStatus(id) {
  for (let i = 0; i < 240; i++) {
    await new Promise(r => setTimeout(r, 1500));
    try {
      const r = await fetch("/api/requests/" + id, {headers: {"X-Pairing-Token": TOKEN}});
      const d = await r.json();
      if (d.state === "completed") { setStatus("Approved ✓ — " + (d.result || "done"), "ok"); return; }
      if (["rejected", "expired", "failed"].includes(d.state)) {
        setStatus(d.state === "failed" ? "Failed: " + d.error : "Request " + d.state, "err"); return;
      }
    } catch (e) { /* keep polling */ }
  }
  setStatus("Timed out waiting for approval", "err");
}

document.getElementById("sendBtn").addEventListener("click", () => {
  const v = document.getElementById("manual").value.trim();
  if (!v) { setStatus("Paste a link first", "err"); return; }
  relay(v);
});
if (DEMO) {
  demoBtn.classList.remove("hidden");
  demoBtn.addEventListener("click", () => relay(
    "ton://transfer/UQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJKZ?amount=1000000000&text=demo-scan"));
}

// Camera scanning via the native BarcodeDetector (Chrome/Safari on mobile).
async function startCamera() {
  if (!("BarcodeDetector" in window)) {
    cameraStatus.textContent = "QR scanning not supported by this browser — use manual paste below.";
    video.classList.add("hidden");
    return;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({video: {facingMode: "environment"}});
  } catch (e) {
    cameraStatus.textContent = "Camera unavailable (" + e.name + ") — use manual paste below.";
    video.classList.add("hidden");
    return;
  }
  video.srcObject = stream;
  await video.play();
  stopBtn.classList.remove("hidden");
  const detector = new BarcodeDetector({formats: ["qr_code"]});
  scanning = true;
  const tick = async () => {
    while (scanning) {
      try {
        const codes = await detector.detect(video);
        if (codes.length) { scanning = false; stopCamera(); relay(codes[0].rawValue); return; }
      } catch (e) { /* frame not ready */ }
      await new Promise(r => setTimeout(r, 300));
    }
  };
  cameraStatus.textContent = "Point the camera at a QR code";
  tick();
}
function stopCamera() {
  scanning = false;
  if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
  video.srcObject = null;
  video.classList.add("hidden");
  stopBtn.classList.add("hidden");
  cameraStatus.textContent = "Camera stopped — paste manually or reload to scan again.";
}
stopBtn.addEventListener("click", stopCamera);
startCamera();
</script>
</body>
</html>
"""
