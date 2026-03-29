import os
import sys
import threading
import time
import subprocess
import requests
import asyncio
import logging
import datetime
import traceback
import smtplib
from email.message import EmailMessage
from flask import Flask, render_template_string, request, jsonify
from dotenv import load_dotenv

# Twilio
from twilio.rest import Client as TwilioClient
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.twiml.voice_response import VoiceResponse

# VideoSDK Agents
from videosdk.agents import (
    Agent, AgentSession, RealTimePipeline, JobContext,
    RoomOptions, WorkerJob, Options, function_tool
)
from videosdk.plugins.google import GeminiRealtime, GeminiLiveConfig

# Google Calendar
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# --- Configuration & Restore ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# Restoration of token.json (Render persistence trick)
if not os.path.exists("token.json"):
    token_data = os.getenv("GOOGLE_TOKEN_DATA")
    if token_data:
        with open("token.json", "w") as f:
            f.write(token_data)
        logging.info("✅ Restored token.json from ENV")

# --- Globals & Env ---
USER_NAME = os.getenv("USER_NAME", "User")
TRANSFER_NUMBER = os.getenv("TRANSFER_NUMBER")
VIDEOSDK_TOKEN = os.getenv("VIDEOSDK_TOKEN")
if VIDEOSDK_TOKEN:
    os.environ["VIDEOSDK_AUTH_TOKEN"] = VIDEOSDK_TOKEN

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE = os.getenv("TWILIO_PHONE_NUMBER")
twilio_client = TwilioClient(TWILIO_SID, TWILIO_TOKEN) if TWILIO_SID else None

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TWIML_APP_SID = None
API_KEY_SID = None
API_KEY_SECRET = None
transfer_state = {}

# --- HELPER: Google Calendar ---
def get_calendar_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                 raise Exception("Missing credentials.json")
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)

def send_summary_email(summary: str):
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    receiver = os.getenv("EMAIL_RECEIVER")
    if not all([sender, password, receiver]):
        logging.warning("⚠️ Email not configured in .env")
        return
    try:
        msg = EmailMessage()
        msg.set_content(f"📞 สรุปการสนทนา:\n{summary}")
        msg["Subject"] = "แจ้งเตือน: สรุปการโทรจาก AI Assistant"
        msg["From"] = sender
        msg["To"] = receiver
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(sender, password)
            s.send_message(msg)
        logging.info("📧 ส่ง Email สำเร็จ!")
    except Exception as e:
        logging.error(f"Email error: {e}")

# --- AI AGENT LOGIC (from main.py) ---
INSTRUCTIONS = f"""คุณคือ AI ผู้ช่วยรับสายโทรศัพท์แทนคุณ{USER_NAME} (ตอบกลับเป็นภาษาไทยเท่านั้น)
ตอบกลับให้กระชับ เป็นธรรมชาติ สุภาพ และเป็นมิตร

[การสนทนา]:
-เริ่มต้นด้วยการพูดว่า"ฉันคือ AI ผู้ช่วยรับสายโทรศัพท์แทนคุณ{USER_NAME} มีธุระอะไรกับคุณ{USER_NAME}หรือป่าว"
- ถ้าถามหาเวลาว่าง/นัดหมาย ให้แปลงวันที่เป็น YYYY-MM-DD แล้วใช้ `check_calendar`

[นัดหมาย]:
- ถ้าผู้โทรต้องการนัดพบ/จองเวลา ให้:
  1. ถามวันที่ เวลาเริ่ม เวลาจบ และหัวข้อ
  2. ใช้ `check_calendar` ตรวจว่าช่วงเวลานั้นว่างหรือไม่
  3. ถ้าว่าง ใช้ `create_event` สร้างนัดหมาย
  4. ยืนยันกับผู้โทรว่าสร้างสำเร็จแล้ว

[โอนสาย]:
    ถ้าผู้โทรถามหา “คุณ{USER_NAME}” หรือขอคุยกับคนจริง:
    ใช้ check_calendar เพื่อตรวจสอบก่อน
    ถ้าไม่มีนัด → สามารถโอนสายได้
    ให้ถามยืนยันกับผู้โทรว่าต้องการโอนสายใช่ไหม
    เมื่อผู้โทรยืนยันให้โอนสาย
    ใช้ transfer_call ด้วยเบอร์ {TRANSFER_NUMBER}
    หลังเรียก tool ให้พูดว่า:
    "กำลังโอนสายให้ค่ะ กรุณารอสักครู่นะคะ"

[ตรวจจับ Scammer]:
- ถ้าพบสัญญาณ scam (ขอข้อมูลส่วนตัว/เร่งรีบ/อ้างหน่วยงานรัฐ):
  1. พูดเตือนและวางสาย
  2. ใช้ `flag_scammer`

[วางสาย]:
- กล่าวลาแล้วใช้ `end_call_and_summarize`"""

class MyVoiceAgent(Agent):
    def __init__(self):
        super().__init__(instructions=INSTRUCTIONS)

    async def on_enter(self):
        # Check for transfer flag
        try:
            flag_path = os.path.join(os.path.dirname(__file__) or ".", "_transfer_flag")
            if os.path.exists(flag_path):
                with open(flag_path, "r") as f:
                    ts = float(f.read().strip())
                if time.time() - ts < 30:
                    os.remove(flag_path)
                    logging.info("🚪 AI detected transfer → silent exit")
                    asyncio.create_task(self._leave_after(2))
                    return
        except: pass
        await asyncio.sleep(1)
        await self.session.say(f"สวัสดีค่ะ ฉันคือผู้ช่วยรับสายแทนคุณ{USER_NAME} มีอะไรให้ช่วยไหมคะ?")

    async def on_user_started_speaking(self, user):
        self.session.interrupt()

    @function_tool
    async def end_call_and_summarize(self, summary: str) -> dict:
        send_summary_email(summary)
        async def _delayed_close():
            await asyncio.sleep(3)
            try: await getattr(self.session, "room", self.session).disconnect()
            except: pass
        asyncio.create_task(_delayed_close())
        return {"status": "success"}

    @function_tool
    async def transfer_call(self, phone_number: str) -> dict:
        logging.info(f"🛠️ โอนสายไปที่ {phone_number}")
        try:
            # ใช้ 127.0.0.1:PORT ของตัวเอง
            port = os.getenv("PORT", "5000")
            resp = await asyncio.get_running_loop().run_in_executor(
                None, lambda: requests.post(f"http://127.0.0.1:{port}/transfer_call", json={"phoneNumber": phone_number}, timeout=5)
            )
            if resp.status_code in [200, 201, 202]:
                send_summary_email(f"ผู้โทรขอโอนสาย ({phone_number})")
                asyncio.create_task(self._leave_after(15))
                return {"status": "success"}
            return {"status": "error"}
        except: return {"status": "error"}

    async def _leave_after(self, s):
        await asyncio.sleep(s)
        try: await getattr(self.session, "room", self.session).disconnect()
        except: pass

    @function_tool
    async def check_calendar(self, date_str: str) -> dict:
        try:
            service = get_calendar_service()
            start = datetime.datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=datetime.timezone(datetime.timedelta(hours=7)))
            events = service.events().list(calendarId="primary", timeMin=start.isoformat(), timeMax=(start+datetime.timedelta(days=1)).isoformat(), singleEvents=True).execute().get("items", [])
            if not events: return {"message": f"วันที่ {date_str} ว่างทั้งวันค่ะ"}
            items = [f"- {e['start'].get('dateTime', e['start'].get('date'))[11:16]} {e.get('summary', 'ธุระ')}" for e in events]
            return {"message": "\n".join(items)}
        except: return {"message": "ผิดพลาด"}

    @function_tool
    async def create_event(self, date_str, start_time, end_time, title, description=""):
        try:
            service = get_calendar_service()
            tz = datetime.timezone(datetime.timedelta(hours=7))
            start_dt = datetime.datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
            end_dt = datetime.datetime.strptime(f"{date_str} {end_time}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
            service.events().insert(calendarId="primary", body={
                "summary": title, "description": description or f"AIn Appointment",
                "start": {"dateTime": start_dt.isoformat(), "timeZone": "Asia/Bangkok"},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": "Asia/Bangkok"},
            }).execute()
            return {"message": "สร้างสำเร็จ"}
        except: return {"message": "ล้มเทลว"}

    @function_tool
    async def flag_scammer(self, reason: str) -> dict:
        send_summary_email(f"🚨 SCAM! {reason}")
        asyncio.create_task(self.session.close())
        return {"status": "scammer_flagged"}

async def start_session(context: JobContext):
    model = GeminiRealtime(model="gemini-2.5-flash-native-audio-preview-09-2025", api_key=os.getenv("GOOGLE_API_KEY"), config=GeminiLiveConfig(voice="Leda", response_modalities=["AUDIO"]))
    pipeline = RealTimePipeline(model=model)
    if not hasattr(pipeline, "_current_utterance_handle"): pipeline._current_utterance_handle = None 
    agent = MyVoiceAgent()
    session = AgentSession(agent=agent, pipeline=pipeline)
    try:
        await context.connect()
        await session.start()
        await asyncio.Event().wait()
    finally:
        await session.close()
        await context.shutdown()

# --- WEB SERVER LOGIC (from app.py) ---
def get_public_url():
    url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("NGROK_URL")
    if url: return url.rstrip("/")
    try:
        r = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=1)
        return r.json()["tunnels"][0]["public_url"]
    except: pass
    return None

def get_twiml_app_sid():
    global TWIML_APP_SID
    if TWIML_APP_SID: return TWIML_APP_SID
    pub_url = get_public_url()
    if not pub_url: return None
    voice_url = f"{pub_url}/twilio_voice"
    apps = twilio_client.applications.list(friendly_name="PCAS Combined")
    if apps:
        apps[0].update(voice_url=voice_url, voice_method="POST")
        TWIML_APP_SID = apps[0].sid
    else:
        TWIML_APP_SID = twilio_client.applications.create(friendly_name="PCAS Combined", voice_url=voice_url).sid
    return TWIML_APP_SID

def get_api_key():
    global API_KEY_SID, API_KEY_SECRET
    if API_KEY_SID: return API_KEY_SID, API_KEY_SECRET
    key = twilio_client.new_keys.create(friendly_name="PCAS Combined")
    API_KEY_SID, API_KEY_SECRET = key.sid, key.secret
    return API_KEY_SID, API_KEY_SECRET

@app.route('/')
def home():
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="th">
    <head>
        <meta charset="UTF-8">
        <title>AI Voice Assistant</title>
        <script src="https://sdk.videosdk.live/js-sdk/0.0.84/videosdk.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/@twilio/voice-sdk@2.12.1/dist/twilio.min.js"></script>
        <style>
            body { font-family: 'Segoe UI', sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; background: #eef2f7; margin: 0; }
            .card { background: white; padding: 3rem; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); text-align: center; width: 350px; }
            button { background: #1a73e8; color: white; border: none; padding: 15px; border-radius: 8px; font-size: 16px; cursor: pointer; width: 100%; margin-top: 20px; }
            .danger { background: #d93025; display: none; }
        </style>
    </head>
    <body style="background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);">
        <div class="card">
            <h1>🎙️ AI Personal Assistant</h1>
            <p>Ready to help you with your calls</p>
            <button onclick="startCall()" id="btnCall">Call AI Now</button>
            <button onclick="endCall()" id="btnEnd" class="danger">Hang Up</button>
            <div id="status" style="margin-top:20px; font-weight:bold;"></div>
        </div>
        <script>
            let meeting = null;
            async function startCall() {
                document.getElementById('btnCall').disabled = true;
                const res = await fetch('/generate_room', { method: 'POST' });
                const data = await res.json();
                if(!data.success) { alert(data.error); return; }
                window.VideoSDK.config(data.token);
                meeting = window.VideoSDK.initMeeting({ meetingId: data.roomId, name: "User", micEnabled: true });
                meeting.on("meeting-joined", () => {
                    document.getElementById('status').innerText = "Connected to AI";
                    document.getElementById('btnCall').style.display = 'none';
                    document.getElementById('btnEnd').style.display = 'block';
                    startTransferPoll();
                });
                meeting.on("participant-joined", p => {
                    p.on("stream-enabled", s => {
                        if (s.kind !== 'audio') return;
                        const el = document.createElement("audio"); el.autoplay = true;
                        el.srcObject = new MediaStream([s.track]); document.body.appendChild(el);
                    });
                });
                meeting.join();
            }
            function startTransferPoll() {
                setInterval(async () => {
                   const r = await fetch('/transfer_status');
                   const d = await r.json();
                   if (d.hasTransfer) { 
                       if(meeting) meeting.leave();
                       joinTwilio(d.conferenceName); 
                   }
                }, 3000);
            }
            async function joinTwilio(conf) {
                const res = await fetch('/twilio_token');
                const data = await res.json();
                const device = new Twilio.Device(data.token);
                const conn = await device.connect({ params: { conferenceName: conf } });
                document.getElementById('status').innerText = "On Phone Call";
            }
            function endCall() { if(meeting) meeting.leave(); location.reload(); }
        </script>
    </body>
    </html>
    """)

@app.route('/generate_room', methods=['POST'])
def generate_room():
    token = VIDEOSDK_TOKEN
    if not token: return jsonify(success=False, error="No Token"), 500
    try:
        res = requests.post("https://api.videosdk.live/v2/rooms", headers={"Authorization": token}, timeout=5)
        room_id = res.json()["roomId"]
        # TRIGGER LOCAL JOB (This hits our registered worker on 8081)
        requests.post("http://localhost:8081/jobs", json={
            "agent_id": "MyTelephonyAgent",
            "room_id": room_id
        }, timeout=2)
        return jsonify(success=True, roomId=room_id, token=token)
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500

@app.route('/twilio_token')
def get_twilio_token():
    twiml_sid = get_twiml_app_sid()
    api_sid, api_secret = get_api_key()
    token = AccessToken(TWILIO_SID, api_sid, api_secret, identity="web-user")
    token.add_grant(VoiceGrant(outgoing_application_sid=twiml_sid))
    return jsonify(token=token.to_jwt() if not isinstance(token.to_jwt(), bytes) else token.to_jwt().decode())

@app.route('/twilio_voice', methods=['POST'])
def twilio_voice():
    conf_name = request.form.get("conferenceName", "default")
    resp = VoiceResponse()
    resp.dial().conference(conf_name, start_conference_on_enter=True, end_conference_on_exit=True)
    return str(resp), 200, {"Content-Type": "text/xml"}

@app.route('/transfer_call', methods=['POST'])
def handle_transfer():
    phone = request.json.get('phoneNumber')
    conf_name = f"transfer-{int(time.time())}"
    try:
        twilio_client.calls.create(to=phone, from_=TWILIO_PHONE, twiml=f'<Response><Dial><Conference>{conf_name}</Conference></Dial></Response>')
        transfer_state["_latest"] = {"conferenceName": conf_name}
        with open("_transfer_flag", "w") as f: f.write(str(time.time()))
        return jsonify(success=True)
    except Exception as e: return jsonify(success=False, error=str(e)), 500

@app.route('/transfer_status')
def transfer_status():
    latest = transfer_state.pop("_latest", None)
    return jsonify(hasTransfer=bool(latest), conferenceName=latest["conferenceName"] if latest else None)

# --- STARTUP ---
def run_worker():
    """Run the VideoSDK Global Worker in a separate thread"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        options = Options(agent_id="MyTelephonyAgent", register=True, max_processes=1, host="localhost", port=8081)
        job = WorkerJob(entrypoint=start_session, options=options)
        logging.info("🤖 AI Worker starting (Local Registration mode)...")
        job.start()
    except Exception as e:
        logging.error(f"Worker Error: {e}")

if __name__ == '__main__':
    # Start Worker Thread
    worker_thread = threading.Thread(target=run_worker, daemon=True)
    worker_thread.start()
    
    # Start Flask
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"🚀 Combined App running on port: {port}")
    app.run(port=port, host='0.0.0.0', use_reloader=False)
