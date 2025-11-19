# app.py — Passkey Anchored Linking demo with BLE proximity enforcement (~0.5 m)

import asyncio
import base64
import json
import os
import threading
import time
import uuid
from urllib.parse import quote
from typing import Dict

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

from ble_scanner import BleWatcher

# =====================
# GLOBAL STATE
# =====================
sessions: Dict[str, Dict] = {}
ble_seen: Dict[str, float] = {}

# =====================
# BLE CALLBACK
# =====================
def on_ble_sid(sid: str):
    sid = sid.strip().lower()
    now = time.time()

    if sid in ble_seen and now - ble_seen[sid] < 5:
        return
    ble_seen[sid] = now

    print(f"[BLE] 🔔 Advertisement received SID={sid}")

    for session_id, session in sessions.items():
        session_sid = session.get("sid", "").strip().lower()
        if not session_sid:
            continue

        # Match if SID is same or partially overlapping (prefix)
        if sid.startswith(session_sid[:6]) or session_sid.startswith(sid[:6]):
            session["ble_seen"] = True
            print(f"[BLE] ✅ Proximity verified (<0.5 m) for session {session_id} (sid={session_sid})")
            return

    print(f"[BLE] ⚠️ No matching session found for BLE SID={sid}")


def start_ble_thread():
    watcher = BleWatcher(on_ble_sid, threshold=-58)  # -58 ≈ 0.5 m
    t = threading.Thread(target=watcher.run, daemon=True)
    t.start()
    print("[BLE] Scanner thread started (0.5 m enforcement)")


# =====================
# FastAPI app
# =====================
app = FastAPI()


@app.get("/", response_class=HTMLResponse)
async def index():
    sid = uuid.uuid4().hex[:12]
    rp_id = "localhost"
    url = "http://localhost:8889"
    challenge = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")

    session_id = uuid.uuid4().hex
    sessions[session_id] = {
        "sid": sid,
        "challenge": challenge,
        "ble_seen": False,
        "linked": False,
        "created": time.time(),
    }

    payload = json.dumps({"sid": sid, "rpId": rp_id, "url": url})
    img_data = quote(payload)

    # ============ UI HTML (first page + success chat UI) ============
    qr_html = f"""<!DOCTYPE html>
<html>
<head>
  <title>Device Linking</title>
  <style>
    body {{
      margin: 0;
      background: #f6f4ee;
      font-family: "Segoe UI", Arial, sans-serif;
    }}

    .container {{
      display: flex;
      justify-content: center;
      padding-top: 60px;
    }}

    .panel {{
      background: #ffffff;
      border-radius: 16px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.15);
      padding: 32px;
      width: 820px;
      display: flex;
      gap: 40px;
    }}

    .left {{
      flex: 1;
    }}

    .left h2 {{
      font-size: 24px;
      font-weight: 600;
      margin-bottom: 20px;
    }}

    .steps {{
      list-style: none;
      padding: 0;
      margin: 0;
    }}

    .steps li {{
      font-size: 16px;
      margin: 14px 0;
      display: flex;
      gap: 10px;
      align-items: flex-start;
    }}

    .steps-number {{
      width: 22px;
      height: 22px;
      border-radius: 50%;
      border: 1px solid #999;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 13px;
      font-weight: bold;
      flex-shrink: 0;
      background: #fff;
    }}

    .status-box {{
      margin-top: 28px;
      padding: 12px 16px;
      background: #f0f7ef;
      border-radius: 10px;
      border-left: 4px solid #34a853;
      font-size: 15px;
      color: #256d3b;
    }}

    .qr-box {{
      width: 260px;
      height: 260px;
      background: #fff;
      padding: 12px;
      border: 1px solid #ddd;
      border-radius: 10px;
      display: flex;
      justify-content: center;
      align-items: center;
    }}

    #qrimg {{
      width: 100%;
      height: 100%;
      border-radius: 8px;
    }}

    .success-screen {{
      width: 900px;
      height: 540px;
      background: #ffffff;
      border-radius: 16px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.15);
      display: flex;
      overflow: hidden;
    }}

    .chatlist {{
      width: 32%;
      background: #fdfdfd;
      border-right: 1px solid #ddd;
      padding: 16px;
    }}

    .chatlist h3 {{
      margin: 0 0 16px 0;
      font-size: 18px;
      font-weight: 600;
    }}

    .chat-item {{
      padding: 12px;
      border-radius: 8px;
      margin-bottom: 10px;
      border: 1px solid #eee;
      background: #fff;
      cursor: default;
    }}

    .chatwindow {{
      flex: 1;
      background: #f2f2f2;
      display: flex;
      flex-direction: column;
    }}

    .success-header {{
      padding: 16px;
      font-size: 20px;
      font-weight: bold;
      border-bottom: 1px solid #ddd;
      background: #e6f4ea;
      color: #1e8e3e;
      text-align: center;
    }}

    .chat-body {{
      padding: 20px;
      flex: 1;
    }}

    .bubble {{
      max-width: 60%;
      background: #dcf8c6;
      padding: 12px;
      margin: 10px 0;
      border-radius: 12px;
      align-self: flex-start;
      font-size: 15px;
    }}
  </style>
</head>

<body>

<div id="main">

  <!-- BEFORE LINKING -->
  <div id="link-panel" class="container">
    <div class="panel">

      <!-- LEFT: Steps -->
      <div class="left">
        <h2>Steps to Connect</h2>

        <ul class="steps">
          <li><span class="steps-number">1</span>Open the linking app on your phone</li>
          <li><span class="steps-number">2</span>Select “Link a device”</li>
          <li><span class="steps-number">3</span>Point your phone at the QR code</li>
          <li><span class="steps-number">4</span>Approve when prompted</li>
        </ul>

        <div id="status" class="status-box">
          Waiting for proximity confirmation…
        </div>
      </div>

      <!-- RIGHT: QR Box -->
      <div class="right">
        <div class="qr-box">
          <img id="qrimg"
               src="https://api.qrserver.com/v1/create-qr-code/?data={img_data}&size=240x240" />
        </div>
      </div>

    </div>
  </div>

</div>

<!-- SUCCESS UI (Initially Hidden) -->
<div id="success-panel" style="display:none;" class="container">
  <div class="success-screen">

    <div class="chatlist">
      <h3>Chats</h3>
      <div class="chat-item">John Doe</div>
      <div class="chat-item">Alice</div>
      <div class="chat-item">Research Group</div>
      <div class="chat-item">Security Lab</div>
    </div>

    <div class="chatwindow">
      <div class="success-header">Device Linked Successfully</div>
      <div class="chat-body">
        <div class="bubble">Your device was successfully linked.</div>
        <div class="bubble">Secure connection established.</div>
      </div>
    </div>

  </div>
</div>

<script>
async function poll() {{
  const r = await fetch('/status?sid={sid}');
  const j = await r.json();

  const qr = document.getElementById('qrimg');
  const status = document.getElementById('status');

  // BLE detected
  if (j.ble_seen && !j.linked) {{
    if (qr) {{
      qr.style.display = 'none';
    }}
    if (status) {{
      status.innerText = "Proximity verified. Awaiting confirmation…";
      status.style.background = "#eef7ff";
      status.style.borderLeft = "4px solid #1a73e8";
    }}
  }}

  // Linked → show success UI
  if (j.linked) {{
    const linkPanel = document.getElementById("link-panel");
    const successPanel = document.getElementById("success-panel");
    if (linkPanel) {{
      linkPanel.style.display = "none";
    }}
    if (successPanel) {{
      successPanel.style.display = "flex";
    }}
  }}

  setTimeout(poll, 2000);
}}

poll();
</script>

</body>
</html>"""

    print(f"[HTTP] New session created for SID={sid}")
    return HTMLResponse(qr_html)


@app.get("/pair")
async def pair(sid: str):
    for s, v in sessions.items():
        if v["sid"] == sid:
            print(f"[PAIR] Request for SID={sid}")
            return JSONResponse(
                {
                    "challenge": v["challenge"],
                    "sessionId": s,
                }
            )
    return JSONResponse({"error": "unknown sid"}, status_code=404)


@app.post("/webauthn/finish")
async def finish(req: Request):
    body = await req.json()
    session_id = body.get("sessionId")
    user_id = body.get("userId")

    sess = sessions.get(session_id)
    if not sess:
        return JSONResponse({"error": "invalid session"}, status_code=404)

    # Enforce BLE proximity before allowing linking
    if not sess.get("ble_seen"):
        print(f"[FINISH] ❌ Rejected link for session={session_id}: BLE not verified (<0.5 m required)")
        return JSONResponse(
            {"error": "BLE proximity not verified (<0.5 m required)"},
            status_code=403,
        )

    print(f"[FINISH] 🔒 BLE proximity verified for sid={sess['sid']}")
    sess["linked"] = True
    sess["userId"] = user_id
    print(f"[FINISH] ✅ Linked session={session_id} user={user_id}")
    return JSONResponse({"status": "ok"})


@app.get("/status")
async def status(sid: str):
    for s, v in sessions.items():
        if v["sid"] == sid:
            print(f"[STATUS] ✅ Status requested for active sid={sid}")
            return JSONResponse(
                {
                    "ble_seen": v.get("ble_seen", False),
                    "linked": v.get("linked", False),
                    "userId": v.get("userId", None),
                }
            )
    print(f"[STATUS] ⚠️ Unknown sid={sid}")
    return JSONResponse({"ble_seen": False, "linked": False})


@app.get("/link", response_class=HTMLResponse)
async def link_redirect():
    return await index()


# =====================
# Run
# =====================
if __name__ == "__main__":
    start_ble_thread()
    uvicorn.run(app, host="0.0.0.0", port=8889)
hr
