import asyncio
import traceback
import os
import logging
import smtplib
import datetime
from email.message import EmailMessage
from dotenv import load_dotenv

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

logging.basicConfig(level=logging.INFO)
load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/calendar"]
# VIDEOSDK_TOKEN from .env
VIDEOSDK_TOKEN = os.getenv("VIDEOSDK_TOKEN")
if VIDEOSDK_TOKEN:
    os.environ["VIDEOSDK_AUTH_TOKEN"] = VIDEOSDK_TOKEN # Support standard SDK name

USER_NAME = os.getenv("USER_NAME", "จักรพงษ์")
TRANSFER_NUMBER = os.getenv("TRANSFER_NUMBER", "+66924437639")


# ─── Helpers ───────────────────────────────────────────────

def get_calendar_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
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


# ─── AI Agent ──────────────────────────────────────────────

INSTRUCTIONS = f"""คุณคือ AI ผู้ช่วยรับสายโทรศัพท์แทนคุณ{USER_NAME} (ตอบกลับเป็นภาษาไทยเท่านั้น)
ตอบกลับให้กระชับ เป็นธรรมชาติ สุภาพ และเป็นมิตร

[การสนทนา]:
- ผู้โทรพูดแทรกได้ตลอดเวลา ถ้าพูดแทรกให้หยุดฟังทันที
- ถ้าถามหาเวลาว่าง/นัดหมาย ให้แปลงวันที่เป็น YYYY-MM-DD แล้วใช้ `check_calendar`

[นัดหมาย]:
- ถ้าผู้โทรต้องการนัดพบ/จองเวลา ให้:
  1. ถามวันที่ เวลาเริ่ม เวลาจบ และหัวข้อ
  2. ใช้ `check_calendar` ตรวจว่าช่วงเวลานั้นว่างหรือไม่
  3. ถ้าว่าง ใช้ `create_event` สร้างนัดหมาย
  4. ยืนยันกับผู้โทรว่าสร้างสำเร็จแล้ว
- ห้ามลบหรือแก้ไขนัดหมายที่มีอยู่ (ผู้โทรไม่ใช่เจ้าของตาราง)

[โอนสาย]:
- ถ้าผู้โทรถามหา "คุณ{USER_NAME}" หรือขอคุยกับคนจริง ให้เสนอโอนสาย
- พูดว่า "ต้องการให้โอนสายไปหาคุณ{USER_NAME}ไหมคะ? ถ้าไม่รับสายฝากข้อความไว้ได้นะคะ"
- ถ้ายืนยัน ให้ใช้ `transfer_call` ด้วยเบอร์ {TRANSFER_NUMBER}
- ***หลังโอนสำเร็จ พูดว่า "กำลังโอนสายค่ะ กรุณารอสักครู่" แล้วหยุด ห้ามเรียกเครื่องมืออื่น***

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
        # ถ้ามี transfer_flag (สร้างโดย app.py) แปลว่า AI ตัวนี้ถูก spawn มาเพื่อห้องที่กำลังโอนสาย → ออกเงียบๆ ไม่ทักทาย
        import time
        try:
            flag_path = os.path.join(os.path.dirname(__file__), "_transfer_flag")
            if os.path.exists(flag_path):
                with open(flag_path, "r") as f:
                    ts = float(f.read().strip())
                if time.time() - ts < 30:  # ภายใน 30 วินาที
                    os.remove(flag_path)
                    logging.info("🚪 AI ตรวจพบ transfer flag → ออกจากห้องเงียบๆ ใน 2 วินาที")
                    asyncio.create_task(self._leave_after(2))
                    return
        except Exception:
            pass

        await asyncio.sleep(1)
        await self.session.say(f"สวัสดีค่ะ ฉันคือผู้ช่วยรับสายแทนคุณ{USER_NAME} มีอะไรให้ช่วยไหมคะ?")

    async def on_user_started_speaking(self, user):
        self.session.interrupt()

    async def on_exit(self):
        pass  # AI กล่าวลาใน prompt ก่อนเรียก end_call แล้ว

    # ── Tools ──

    @function_tool
    async def end_call_and_summarize(self, summary: str) -> dict:
        """End the call and send a summary email.
        Args:
            summary: สรุปการสนทนาแบบสั้นๆ (ภาษาไทย)
        """
        logging.info(f"🛠️ AI วางสาย: {summary}")
        send_summary_email(summary)
        # สั่งออกจากห้อง (disconnect จาก VideoSDK)
        # รอ 3 วิให้ระบบพูดคำปฏิเสธ/คำบอกลาจบก่อน
        async def _delayed_close():
            await asyncio.sleep(3)
            try:
                # ใช้ .room.disconnect() ให้ AI leave จากห้องแบบ clean ดึง event ฝั่งเว็บ
                await getattr(self.session, "room", self.session).disconnect()
            except Exception:
                try:
                    await self.session.close()
                except Exception:
                    pass
        asyncio.create_task(_delayed_close())
        return {"status": "success"}

    @function_tool
    async def transfer_call(self, phone_number: str) -> dict:
        """Transfer the call to a phone number. AI will leave after transfer.
        Args:
            phone_number: E.164 format phone number (e.g., '+66924437639').
        """
        import requests as req
        logging.info(f"🛠️ โอนสายไปที่ {phone_number}")

        try:
            resp = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: req.post(
                    "http://127.0.0.1:5000/transfer_call",
                    json={"phoneNumber": phone_number},
                    headers={"Content-Type": "application/json"},
                    timeout=10
                )
            )
            if resp.status_code in [200, 201, 202]:
                send_summary_email(f"ผู้โทรขอโอนสายไปหาคุณ{USER_NAME} ({phone_number})")
                # รอ 15 วิ ให้โทรศัพท์เข้าห้อง แล้ว AI ออกเงียบๆ
                asyncio.create_task(self._leave_after(15))
                return {"status": "success", "message": "กำลังโอนสาย กรุณารอสักครู่"}
            return {"status": "error", "message": f"โอนสายล้มเหลว ({resp.status_code})"}
        except Exception as e:
            return {"status": "error", "message": f"ระบบขัดข้อง ({e})"}

    async def _leave_after(self, seconds: int):
        """หน่วงเวลาแล้วออกจากห้องให้คลีนที่สุด"""
        await asyncio.sleep(seconds)
        logging.info("🚪 AI ปิด session และออกจากห้อง")
        try:
            await getattr(self.session, "room", self.session).disconnect()
        except Exception:
            try:
                await self.session.close()
            except Exception:
                pass

    @function_tool
    async def check_calendar(self, date_str: str) -> dict:
        """Check schedule for a specific date.
        Args:
            date_str: Date in YYYY-MM-DD format.
        """
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
        """Create a new calendar event/appointment.
        Args:
            date_str: Date in YYYY-MM-DD format.
            start_time: Start time in HH:MM format (24h), e.g. '10:00'.
            end_time: End time in HH:MM format (24h), e.g. '11:00'.
            title: Event title/summary.
            description: Optional event description.
        """
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

            logging.info(f"✅ สร้างนัดหมายสำเร็จ: {event.get('htmlLink')}")
            return {"message": f"สร้างนัดหมาย '{title}' วันที่ {date_str} เวลา {start_time}-{end_time} สำเร็จแล้วค่ะ"}
        except Exception as e:
            logging.error(f"Calendar create error: {e}")
            return {"message": "ไม่สามารถสร้างนัดหมายได้ค่ะ กรุณาลองใหม่"}

    @function_tool
    async def flag_scammer(self, reason: str) -> dict:
        """Flag the caller as a suspected scammer. Sends alert email and ends the call.
        Args:
            reason: สรุปเหตุผลที่สงสัยว่าเป็น scam (ภาษาไทย)
        """
        logging.warning(f"🚨 SCAM DETECTED: {reason}")
        send_summary_email(f"🚨 แจ้งเตือน SCAM!\n\nเหตุผล: {reason}\n\nระบบวางสายอัตโนมัติแล้ว")
        asyncio.create_task(self.session.close())
        return {"status": "scammer_flagged"}


# ─── Session & Entry ───────────────────────────────────────

async def start_session(context: JobContext):
    model = GeminiRealtime(
        model="gemini-2.5-flash-native-audio-preview-09-2025",
        api_key=os.getenv("GOOGLE_API_KEY"),
        config=GeminiLiveConfig(voice="Leda", response_modalities=["AUDIO"])
    )
    pipeline = RealTimePipeline(model=model)
    if not hasattr(pipeline, "_current_utterance_handle"):
        pipeline._current_utterance_handle = None  # SDK 0.0.67 bug patch

    agent = MyVoiceAgent()
    agent.current_room_id = getattr(context.room_options, "room_id", None)
    session = AgentSession(agent=agent, pipeline=pipeline)

    try:
        await context.connect()
        await session.start()
        await asyncio.Event().wait()
    finally:
        await session.close()
        await context.shutdown()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--room-id", type=str, default=None)
    parser.add_argument("--auth-only", action="store_true", help="Perform auth and exit")
    args = parser.parse_args()

    # Pre-flight: Check Google Calendar Auth (First time login)
    if not os.path.exists("token.json") or args.auth_only:
        logging.info("🔐 Google Calendar auth check...")
        get_calendar_service()
        if args.auth_only:
            logging.info("✅ Auth completed. Exiting.")
            exit(0)
    
    try:
        is_register = not args.room_id
        options = Options(
            agent_id="MyTelephonyAgent",
            register=is_register,
            max_processes=10 if is_register else 1,
            host="localhost", port=8081,
        )
        job = WorkerJob(
            entrypoint=start_session,
            jobctx=lambda: JobContext(room_options=RoomOptions(room_id=args.room_id)),
            options=options,
        )
        job.start()
    except Exception:
        traceback.print_exc()