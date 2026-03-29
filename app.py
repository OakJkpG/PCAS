from flask import Flask, render_template_string, request, jsonify
import requests
import os
import subprocess
import time
import sys
from dotenv import load_dotenv

from twilio.rest import Client as TwilioClient
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.twiml.voice_response import VoiceResponse

load_dotenv()
app = Flask(__name__)

# ─── Restore token.json from ENV (Render Persistence Trick) ──
if not os.path.exists("token.json"):
    token_data = os.getenv("GOOGLE_TOKEN_DATA")
    if token_data:
        with open("token.json", "w") as f:
            f.write(token_data)
        print("✅ Restored token.json from GOOGLE_TOKEN_DATA")

# ─── Twilio Setup ──────────────────────────────────────────

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE = os.getenv("TWILIO_PHONE_NUMBER")
twilio_client = TwilioClient(TWILIO_SID, TWILIO_TOKEN) if TWILIO_SID else None
TWIML_APP_SID = None
API_KEY_SID = None
API_KEY_SECRET = None

# สถานะการโอนสาย (ให้ frontend poll)
transfer_state = {}


def get_public_url():
    """ดึง URL สาธารณะ (จาก RENDER_EXTERNAL_URL หรือ NGROK_URL)"""
    url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("NGROK_URL")
    if url:
        return url.rstrip("/")
    # ลอง auto-detect จาก ngrok local API (กรณีรัน local)
    try:
        r = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=2)
        tunnels = r.json().get("tunnels", [])
        for t in tunnels:
            if t.get("proto") == "https":
                return t["public_url"]
    except Exception:
        pass
    return None


def get_twiml_app_sid():
    """สร้างหรือ reuse TwiML App (ชี้ voice_url ไปที่ URL สาธารณะ)"""
    global TWIML_APP_SID
    if TWIML_APP_SID:
        return TWIML_APP_SID

    pub_url = get_public_url()
    if not pub_url:
        print("⚠️  ไม่พบ Public URL (RENDER_EXTERNAL_URL หรือ NGROK_URL)")
        return None

    voice_url = f"{pub_url}/twilio_voice"
    apps = twilio_client.applications.list(friendly_name="PCAS Transfer")
    
    if apps:
        apps[0].update(voice_url=voice_url, voice_method="POST")
        TWIML_APP_SID = apps[0].sid
    else:
        app_obj = twilio_client.applications.create(
            friendly_name="PCAS Transfer",
            voice_url=voice_url,
            voice_method="POST"
        )
        TWIML_APP_SID = app_obj.sid
        
    print(f"📞 TwiML App: {TWIML_APP_SID} → {voice_url}")
    return TWIML_APP_SID


def get_api_key():
    """สร้าง API Key สำหรับ AccessToken (Voice SDK 2.x ต้องใช้ SK... ไม่ใช่ Account SID)"""
    global API_KEY_SID, API_KEY_SECRET
    if API_KEY_SID:
        return API_KEY_SID, API_KEY_SECRET
    key = twilio_client.new_keys.create(friendly_name="PCAS Voice")
    API_KEY_SID = key.sid
    API_KEY_SECRET = key.secret
    print(f"🔑 API Key created: {API_KEY_SID}")
    return API_KEY_SID, API_KEY_SECRET


# ─── Frontend ──────────────────────────────────────────────

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Voice Assistant</title>
    <script src="https://sdk.videosdk.live/js-sdk/0.0.84/videosdk.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/@twilio/voice-sdk@2.12.1/dist/twilio.min.js"></script>
    <style>
        body { font-family: 'Segoe UI', sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; background: #f0f2f5; margin: 0; }
        .card { background: white; padding: 2.5rem 2rem; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-align: center; width: 100%; max-width: 400px; }
        h1 { color: #1a73e8; font-size: 24px; margin-bottom: 0.5rem; }
        p { color: #5f6368; font-size: 14px; line-height: 1.5; margin-bottom: 2rem; }
        button { background: #1a73e8; color: white; border: none; padding: 14px 24px; border-radius: 8px; font-size: 18px; font-weight: bold; cursor: pointer; width: 100%; }
        button:hover { background: #1557b0; }
        button.danger { background: #db4437; margin-top: 10px; display: none; }
        button:disabled { background: #90b4e8; cursor: not-allowed; }
        .status { margin-top: 1.5rem; font-weight: bold; font-size: 15px; min-height: 24px; }
        .success { color: #0f9d58; } .error { color: #db4437; }
        .logo { width: 80px; height: 80px; background: #e8f0fe; border-radius: 50%; display: flex; justify-content: center; align-items: center; margin: 0 auto 1.5rem; font-size: 36px; }
        @keyframes pulse { 0%,100% { transform: scale(1); } 50% { transform: scale(1.05); } }
    </style>
</head>
<body>
    <div class="card">
        <div class="logo" id="logo">🎙️</div>
        <h1 id="title">โทรคุยกับ AI Assistant</h1>
        <p id="desc">พูดคุยผ่านไมโครโฟนได้โดยตรง<br>ระบบจะดึง AI เข้ามารับสายอัตโนมัติ</p>
        <button onclick="startCall()" id="btnCall">เชื่อมต่อสาย AI ทันที</button>
        <button onclick="endCall()" id="btnEnd" class="danger">วางสาย</button>
        <div id="status" class="status"></div>
    </div>
    <div id="audio" style="display:none"></div>

    <script>
        let meeting = null;
        let twilioConn = null;
        let pollTimer = null;
        const $ = id => document.getElementById(id);

        function attachAudio(m) {
            m.on("participant-joined", p => {
                p.on("stream-enabled", s => {
                    if (s.kind !== 'audio') return;
                    const el = document.createElement("audio");
                    el.autoplay = true; el.id = 'a-' + p.id;
                    el.srcObject = new MediaStream([s.track]);
                    el.play().catch(() => {});
                    $('audio').appendChild(el);
                });
                p.on("stream-disabled", s => {
                    if (s.kind === 'audio') { const el = $('a-' + p.id); if (el) el.remove(); }
                });
            });
            m.on("participant-left", p => {
                const el = $('a-' + p.id); if (el) el.remove();
                if (!twilioConn) {
                    $('status').innerHTML = '<span class="success">ℹ️ สิ้นสุดการสนทนาโดย AI</span>';
                    setTimeout(() => endCall(), 1500);
                }
            });
        }

        async function startCall() {
            $('btnCall').disabled = true;
            $('btnCall').innerText = 'กำลังเปิดห้อง...';
            try {
                const res = await fetch('/generate_room', { method: 'POST' });
                const data = await res.json();
                if (!data.success) throw new Error(data.error);

                window.VideoSDK.config(data.token);
                meeting = window.VideoSDK.initMeeting({
                    meetingId: data.roomId, name: "User (Web)",
                    micEnabled: true, webcamEnabled: false,
                });
                meeting.on("meeting-joined", () => {
                    $('status').innerHTML = '<span class="success">✅ อยู่ในสายแล้ว รอ AI ทักทาย...</span>';
                    $('btnCall').style.display = 'none';
                    $('btnEnd').style.display = 'block';
                    $('logo').innerText = '🔊';
                    $('logo').style.background = '#ceead6';
                    $('logo').style.animation = 'pulse 1.5s infinite';
                    $('title').innerText = 'กำลังสนทนากับ AI';
                    $('desc').innerText = 'พูดคุยได้เลย หากต้องการโอนสายให้บอก AI';
                    startTransferPoll();
                });
                meeting.on("meeting-left", () => { clearInterval(pollTimer); resetUI(); });
                attachAudio(meeting);
                meeting.join();
            } catch (err) {
                $('status').innerHTML = '<span class="error">❌ ' + err.message + '</span>';
                resetUI();
            }
        }

        function startTransferPoll() {
            pollTimer = setInterval(async () => {
                try {
                    const r = await fetch('/transfer_status');
                    const d = await r.json();
                    if (!d.hasTransfer) return;
                    clearInterval(pollTimer);
                    $('status').innerHTML = '<span class="success">📞 กำลังเชื่อมต่อสายโทรศัพท์...</span>';
                    if (meeting) { meeting.leave(); meeting = null; }
                    await joinTwilioConference(d.conferenceName);
                } catch(e) { console.error(e); }
            }, 3000);
        }

        async function joinTwilioConference(confName) {
            try {
                const res = await fetch('/twilio_token');
                const data = await res.json();
                if (data.error) throw new Error(data.error);
                const device = new Twilio.Device(data.token, { logLevel: 1 });
                twilioConn = await device.connect({ params: { conferenceName: confName } });
                twilioConn.on('accept', () => {
                    $('status').innerHTML = '<span class="success">✅ เชื่อมต่อสายโทรศัพท์สำเร็จ! คุยกันได้เลย</span>';
                    $('title').innerText = '📞 สนทนาสด';
                    $('desc').innerText = 'คุณกำลังคุยกับโทรศัพท์โดยตรง';
                    $('btnEnd').style.display = 'block';
                });
                twilioConn.on('disconnect', () => { resetUI(); });
                window._twilioDevice = device;
            } catch(e) {
                $('status').innerHTML = '<span class="error">❌ ' + e.message + '</span>';
            }
        }

        function endCall() {
            if (window._twilioDevice) { window._twilioDevice.disconnectAll(); window._twilioDevice.destroy(); window._twilioDevice = null; twilioConn = null; }
            if (meeting) { meeting.leave(); }
        }

        function resetUI() {
            $('btnCall').style.display = 'block';
            $('btnCall').disabled = false;
            $('btnCall').innerText = 'โทรหา AI อีกครั้ง';
            $('btnEnd').style.display = 'none';
            $('logo').innerText = '🎙️';
            $('logo').style.background = '#e8f0fe';
            $('logo').style.animation = 'none';
            $('title').innerText = 'โทรคุยกับ AI Assistant';
            $('desc').innerText = 'สายถูกวางแล้ว เริ่มใหม่ได้';
            $('status').innerHTML = '';
            $('audio').innerHTML = '';
            meeting = null; twilioConn = null;
        }
    </script>
</body>
</html>
"""

# ─── API Routes ────────────────────────────────────────────

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)


@app.route('/generate_room', methods=['POST'])
def generate_room():
    token = os.getenv("VIDEOSDK_TOKEN")
    if not token:
        return jsonify(success=False, error="Missing VIDEOSDK_TOKEN"), 500
    try:
        res = requests.post("https://api.videosdk.live/v2/rooms",
                            headers={"Authorization": token}, timeout=10)
        if res.status_code != 200:
            return jsonify(success=False, error=f"API {res.status_code}"), 400
        room_id = res.json()["roomId"]
        # ใช้ sys.executable แทน "python" เพื่อความแม่นยำใน container
        subprocess.Popen([sys.executable, "main.py", "--room-id", room_id])
        print(f"🤖 AI Agent started for room: {room_id}")
        return jsonify(success=True, roomId=room_id, token=token)
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500


@app.route('/twilio_token')
def get_twilio_token():
    twiml_sid = get_twiml_app_sid()
    if not twiml_sid:
        return jsonify(error="TwiML App not configured."), 500
    api_sid, api_secret = get_api_key()
    token = AccessToken(
        TWILIO_SID, api_sid, api_secret,
        identity="web-user"
    )
    voice_grant = VoiceGrant(
        outgoing_application_sid=twiml_sid,
        incoming_allow=False
    )
    token.add_grant(voice_grant)
    jwt = token.to_jwt()
    if isinstance(jwt, bytes):
        jwt = jwt.decode("utf-8")
    return jsonify(token=jwt)


@app.route('/twilio_voice', methods=['POST'])
def twilio_voice():
    conf_name = request.form.get("conferenceName", "default")
    resp = VoiceResponse()
    dial = resp.dial()
    dial.conference(
        conf_name,
        start_conference_on_enter=True,
        end_conference_on_exit=True
    )
    return str(resp), 200, {"Content-Type": "text/xml"}


@app.route('/transfer_call', methods=['POST'])
def handle_transfer():
    phone = request.json.get('phoneNumber')
    if not phone:
        return jsonify(success=False, error="Missing phoneNumber"), 400

    conf_name = f"transfer-{int(time.time())}"

    try:
        call = twilio_client.calls.create(
            to=phone,
            from_=TWILIO_PHONE,
            twiml=f'<Response><Dial><Conference startConferenceOnEnter="true" endConferenceOnExit="false">{conf_name}</Conference></Dial></Response>'
        )
        transfer_state["_latest"] = {"conferenceName": conf_name}
        flag_path = os.path.join(os.path.dirname(__file__) or ".", "_transfer_flag")
        with open(flag_path, "w") as f:
            f.write(str(time.time()))
        return jsonify(success=True, conferenceName=conf_name)
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500


@app.route('/transfer_status')
def transfer_status():
    latest = transfer_state.pop("_latest", None)
    if latest:
        return jsonify(hasTransfer=True, conferenceName=latest["conferenceName"])
    return jsonify(hasTransfer=False)


# ─── Start ─────────────────────────────────────────────────

if __name__ == '__main__':
    # Pre-flight check for Google Calendar (Only try to login if not in prod or if token exists)
    # ใน Production เราจะเน้น Restoration จาก ENV แทน
    if not os.path.exists("token.json") and os.path.exists("credentials.json"):
        print("🔐 First-time login check...")
        subprocess.run([sys.executable, "main.py", "--auth-only"])

    pub_url = get_public_url()
    print("=" * 50)
    if pub_url:
        print(f"🌐 Public/Production URL: {pub_url}")
        get_twiml_app_sid()  # Pre-create/Update TwiML App
    else:
        print("⚠️  Working in strictly Local mode (No public URL found)")
    
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Server running on port: {port}")
    print("=" * 50)
    
    app.run(port=port, host='0.0.0.0', use_reloader=False)
