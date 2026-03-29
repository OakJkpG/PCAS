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

# ─── Configuration & Restore ───────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# Restore token.json from ENV (Render Persistence Trick)
if not os.path.exists("token.json"):
    token_data = os.getenv("GOOGLE_TOKEN_DATA")
    if token_data:
        with open("token.json", "w") as f:
            f.write(token_data)
        logging.info("✅ Restored token.json from GOOGLE_TOKEN_DATA")

# ─── Globals & Environment ──────────────────────────────────
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

# ─── Helpers: Google Calendar & Email ───────────────────────
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

# ─── AI Agent Logic (from main.py) ──────────────────────────
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
- ห้ามลบหรือแก้ไขนัดหมายที่มีอยู่ (ผู้โทรไม่ใช่เจ้าของตาราง)

[โอนสาย]:
    ถ้าผู้โทรถามหา “คุณ{USER_NAME}” หรือขอคุยกับคนจริง:
    ใช้ check_calendar เพื่อตรวจสอบก่อน
    ถ้าไม่มีนัด → สามารถโอนสายได้
    ให้ถามยืนยันกับผู้โทรว่าต้องการโอนสายใช่ไหม
    เมื่อผู้โทรยืนยันให้โอนสาย
    ใช้ transfer_call ด้วยเบอร์ {TRANSFER_NUMBER}
    หลังเรียก tool ให้พูดว่า:
    "กำลังโอนสายให้ค่ะ กรุณารอสักครู่นะคะ"
    ถ้ามีนัดให้ ให้เขาสู่กระบวนการ [กรณีปลายทางไม่รับสาย / ติดต่อไม่ได้]
    ถ้าผู้โทรบอกว่า เรื่องด่วนให้ทำการโอนสาย
    
    [กรณีปลายทางไม่รับสาย / ติดต่อไม่ได้]
    ถ้าโอนสายไม่สำเร็จ หรือไม่มีการรับสายภายในระยะเวลาที่กำหนด ให้พูดว่า:

    "ขออภัยค่ะ ขณะนี้คุณ{USER_NAME}ไม่สะดวกรับสาย
    หากต้องการ ดิฉันสามารถรับข้อความไว้ให้ได้นะคะ"

    ถ้าผู้โทรต้องการฝากข้อความ:
    ให้ถามต่อ:
    "รบกวนแจ้งข้อความที่ต้องการฝากได้เลยค่ะ"

[ตรวจจับ Scammer]:
- ระหว่างสนทนา ใช้สัญญาณเหล่านี้ตัดสินว่าเป็น scam:
  * ขอข้อมูลธนาคาร/เลขบัญชี/รหัส OTP/PIN
  * อ้างตัวเป็นธนาคาร ตำรวจ ศาล หรือหน่วยงานรัฐ แล้วขู่/เร่งรีบ
  * สร้างความตกใจ เช่น "บัญชีจะถูกอายัด" "มีหมายจับ"
  * ขอให้โอนเงิน/มัดจำ/ค่าธรรมเนียม
- ถ้าพบสัญญาณ scam 2 อย่างขึ้นไป:
  1. พูดว่า "ขออภัยค่ะ ดิฉันตรวจพบว่าบทสนทนานี้มีลักษณะคล้ายการหลอกลวง ขอวางสายนะคะ"
  2. ใช้ `flag_scammer` ส่งแจ้งเตือนและวางสาย

[วางสาย]:
- เมื่อสนทนาจบหรือผู้โทรบอกลา ให้กล่าวลาแล้วใช้ `end_call_and_summarize` พร้อมสรุป"""

class MyVoiceAgent(Agent):
    def __init__(self):
        super().__init__(instructions=INSTRUCTIONS)

    async def on_enter(self):
        try:
            flag_path = os.path.join(os.path.dirname(__file__) or ".", "_transfer_flag")
            if os.path.exists(flag_path):
                with open(flag_path, "r") as f:
                    ts = float(f.read().strip())
                if time.time() - ts < 30:
                    os.remove(flag_path)
                    logging.info("🚪 AI Agent ตรวจพบ transfer flag → ออกจากห้องเงียบๆ ใน 2 วินาที")
                    asyncio.create_task(self._leave_after(2))
                    return
        except Exception: pass

        await asyncio.sleep(1)
        await self.session.say(f"สวัสดีค่ะ ฉันคือผู้ช่วยรับสายแทนคุณ{USER_NAME} มีอะไรให้ช่วยไหมคะ?")

    async def on_user_started_speaking(self, user):
        self.session.interrupt()

    @function_tool
    async def end_call_and_summarize(self, summary: str) -> dict:
        """End the call and send a summary email."""
        logging.info(f"🛠️ AI วางสาย: {summary}")
        send_summary_email(summary)
        async def _delayed_close():
            await asyncio.sleep(3)
            try:
                await getattr(self.session, "room", self.session).disconnect()
            except Exception:
                try: await self.session.close()
                except Exception: pass
        asyncio.create_task(_delayed_close())
        return {"status": "success"}

    @function_tool
    async def transfer_call(self, phone_number: str) -> dict:
        """Transfer the call to a phone number."""
        import requests as req
        logging.info(f"🛠️ โอนสายไปที่ {phone_number}")
        try:
            port = os.getenv("PORT", "5000")
            resp = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: req.post(
                    f"http://127.0.0.1:{port}/transfer_call",
                    json={"phoneNumber": phone_number},
                    headers={"Content-Type": "application/json"},
                    timeout=10
                )
            )
            if resp.status_code in [200, 201, 202]:
                send_summary_email(f"ผู้โทรขอโอนสายไปหาคุณ{USER_NAME} ({phone_number})")
                asyncio.create_task(self._leave_after(15))
                return {"status": "success", "message": "กำลังโอนสาย กรุณารอสักครู่"}
            return {"status": "error", "message": f"โอนสายล้มเหลว ({resp.status_code})"}
        except Exception as e:
            return {"status": "error", "message": f"ระบบขัดข้อง ({e})"}

    async def _leave_after(self, seconds: int):
        await asyncio.sleep(seconds)
        logging.info("🚪 AI ปิด session และออกจากห้อง")
        try:
            await getattr(self.session, "room", self.session).disconnect()
        except Exception:
            try: await self.session.close()
            except Exception: pass

    @function_tool
    async def check_calendar(self, date_str: str) -> dict:
        """Check schedule for a specific date."""
        logging.info(f"🛠️ ตรวจสอบปฏิทิน: {date_str}")
        try:
            service = get_calendar_service()
            start = datetime.datetime.strptime(date_str, "%Y-%m-%d").replace(
                tzinfo=datetime.timezone(datetime.timedelta(hours=7))
            )
            end = start + datetime.timedelta(days=1)
            events = service.events().list(
                calendarId="primary",
                timeMin=start.isoformat(), timeMax=end.isoformat(),
                singleEvents=True, orderBy="startTime"
            ).execute().get("items", [])

            if not events:
                return {"message": f"วันที่ {date_str} ว่างทั้งวันค่ะ"}
            items = []
            for e in events:
                s = e["start"].get("dateTime", e["start"].get("date", ""))
                items.append(f"- {s[11:16]} {e.get('summary', 'ธุระ')}")
            return {"message": f"วันที่ {date_str} มีกำหนดการ:\n" + "\n".join(items)}
        except Exception as e:
            logging.error(f"Calendar error: {e}")
            return {"message": "ไม่สามารถดึงข้อมูลปฏิทินได้ค่ะ"}

    @function_tool
    async def create_event(self, date_str: str, start_time: str, end_time: str, title: str, description: str = "") -> dict:
        """Create a new calendar event/appointment."""
        logging.info(f"🛠️ สร้างนัดหมาย: {date_str} {start_time}-{end_time} '{title}'")
        try:
            service = get_calendar_service()
            tz = datetime.timezone(datetime.timedelta(hours=7))
            start_dt = datetime.datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
            end_dt = datetime.datetime.strptime(f"{date_str} {end_time}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)

            event = service.events().insert(calendarId="primary", body={
                "summary": title,
                "description": description or f"นัดหมายโดย AI Assistant",
                "start": {"dateTime": start_dt.isoformat(), "timeZone": "Asia/Bangkok"},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": "Asia/Bangkok"},
            }).execute()
            return {"message": f"สร้างนัดหมาย '{title}' วันที่ {date_str} เวลา {start_time}-{end_time} สำเร็จแล้วค่ะ"}
        except Exception as e:
            logging.error(f"Calendar create error: {e}")
            return {"message": "ไม่สามารถสร้างนัดหมายได้ค่ะ กรุณาลองใหม่"}

    @function_tool
    async def flag_scammer(self, reason: str) -> dict:
        """Flag the caller as a suspected scammer."""
        logging.warning(f"🚨 SCAM DETECTED: {reason}")
        send_summary_email(f"🚨 แจ้งเตือน SCAM!\n\nเหตุผล: {reason}\n\nระบบวางสายอัตโนมัติแล้ว")
        asyncio.create_task(self.session.close())
        return {"status": "scammer_flagged"}

async def start_session(context: JobContext):
    model = GeminiRealtime(
        model="gemini-2.5-flash-native-audio-preview-09-2025",
        api_key=os.getenv("GOOGLE_API_KEY"),
        config=GeminiLiveConfig(voice="Leda", response_modalities=["AUDIO"])
    )
    pipeline = RealTimePipeline(model=model)
    if not hasattr(pipeline, "_current_utterance_handle"):
        pipeline._current_utterance_handle = None 
    agent = MyVoiceAgent()
    session = AgentSession(agent=agent, pipeline=pipeline)
    try:
        await context.connect()
        await session.start()
        await asyncio.Event().wait()
    finally:
        await session.close()
        await context.shutdown()

# ─── Web Server Logic (from app.py) ─────────────────────────
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
        app_obj = twilio_client.applications.create(friendly_name="PCAS Combined", voice_url=voice_url, voice_method="POST")
        TWIML_APP_SID = app_obj.sid
    return TWIML_APP_SID

def get_api_key():
    global API_KEY_SID, API_KEY_SECRET
    if API_KEY_SID: return API_KEY_SID, API_KEY_SECRET
    key = twilio_client.new_keys.create(friendly_name="PCAS Combined")
    API_KEY_SID, API_KEY_SECRET = key.sid, key.secret
    return API_KEY_SID, API_KEY_SECRET

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

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/generate_room', methods=['POST'])
def generate_room():
    token = VIDEOSDK_TOKEN
    if not token: return jsonify(success=False, error="No Token"), 500
    try:
        res = requests.post("https://api.videosdk.live/v2/rooms", headers={"Authorization": token}, timeout=5)
        room_id = res.json()["roomId"]
        # Trigger internal worker job via port 8081
        requests.post("http://localhost:8081/jobs", json={"agent_id": "MyTelephonyAgent", "room_id": room_id}, timeout=2)
        return jsonify(success=True, roomId=room_id, token=token)
    except Exception as e: return jsonify(success=False, error=str(e)), 500

@app.route('/twilio_token')
def get_twilio_token():
    twiml_sid = get_twiml_app_sid()
    api_sid, api_secret = get_api_key()
    token = AccessToken(TWILIO_SID, api_sid, api_secret, identity="web-user")
    token.add_grant(VoiceGrant(outgoing_application_sid=twiml_sid))
    jwt = token.to_jwt()
    if isinstance(jwt, bytes): jwt = jwt.decode("utf-8")
    return jsonify(token=jwt)

@app.route('/twilio_voice', methods=['POST'])
def twilio_voice():
    conf_name = request.form.get("conferenceName", "default")
    resp = VoiceResponse()
    resp.dial().conference(conf_name, start_conference_on_enter=True, end_conference_on_exit=True)
    return str(resp), 200, {"Content-Type": "text/xml"}

@app.route('/transfer_call', methods=['POST'])
def handle_transfer():
    phone = request.json.get('phoneNumber')
    if not phone: return jsonify(success=False, error="Missing phoneNumber"), 400
    conf_name = f"transfer-{int(time.time())}"
    try:
        twilio_client.calls.create(to=phone, from_=TWILIO_PHONE, twiml=f'<Response><Dial><Conference startConferenceOnEnter="true" endConferenceOnExit="false">{conf_name}</Conference></Dial></Response>')
        transfer_state["_latest"] = {"conferenceName": conf_name}
        with open("_transfer_flag", "w") as f: f.write(str(time.time()))
        return jsonify(success=True, conferenceName=conf_name)
    except Exception as e: return jsonify(success=False, error=str(e)), 500

@app.route('/transfer_status')
def transfer_status():
    latest = transfer_state.pop("_latest", None)
    if latest: return jsonify(hasTransfer=True, conferenceName=latest["conferenceName"])
    return jsonify(hasTransfer=False)

# ─── Startup Logic: Flask in Thread, Worker in Main ──────────
def run_flask():
    """Run Flask in a background thread"""
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"🚀 Flask Web Server starting on port: {port}")
    app.run(port=port, host='0.0.0.0', use_reloader=False)

if __name__ == '__main__':
    # 1. Start Flask in Background Thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logging.info("✨ Flask thread launched.")
    
    # 2. Start VideoSDK Worker in MAIN THREAD
    try:
        options = Options(agent_id="MyTelephonyAgent", register=True, max_processes=1, host="localhost", port=8081)
        job = WorkerJob(entrypoint=start_session, options=options)
        logging.info("🤖 VideoSDK AI Worker starting in Main Thread...")
        job.start()
    except Exception as e:
        logging.error(f"FATAL Worker Error: {e}")
        while True: time.sleep(60)
