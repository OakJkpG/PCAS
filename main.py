import asyncio
import traceback
from videosdk.agents import Agent, AgentSession, RealTimePipeline, JobContext, RoomOptions, WorkerJob, Options, function_tool
from videosdk.plugins.google import GeminiRealtime, GeminiLiveConfig
from dotenv import load_dotenv
import os
import logging
import smtplib
from email.message import EmailMessage

# เพิ่มไลบรารีของ Google Calendar
import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logging.basicConfig(level=logging.INFO)
load_dotenv()

# กำหนดสิทธิ์ให้แค่ "อ่าน" ปฏิทินได้อย่างเดียวเพื่อความปลอดภัย
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# 1. ฟังก์ชันตัวช่วยสำหรับเชื่อมต่อปฏิทิน
def get_calendar_service():
    creds = None
    # ระบบจะสร้าง token.json ขึ้นมาเก็บไว้หลังจากการล็อกอินครั้งแรก
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0) # จะเปิดหน้าเว็บให้ล็อกอิน
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


class MyVoiceAgent(Agent):
    def __init__(self):
        super().__init__(
            # (Prompt ยังคงเหมือนเดิม บังคับให้ AI สรุปเนื้อหาก่อนวางสาย)
            instructions="""คุณคือ AI ผู้ช่วยรับสายโทรศัพท์แทนคุณจักรพงษ์ (ตอบกลับเป็นภาษาไทยเท่านั้น)
            ตอบกลับให้กระชับ เป็นธรรมชาติ สุภาพ และเป็นมิตร 
            
            [กฎสำคัญเรื่องการสนทนา]: 
            ผู้โทรสามารถพูดแทรกคุณได้ตลอดเวลา หากผู้โทรพูดแทรก ให้หยุดและรับฟังสิ่งที่ผู้โทรพูดใหม่ทันที
            หากผู้โทรต้องการนัดหมาย หรือถามหาเวลาว่าง ให้แปลงวันที่เป็นรูปแบบ YYYY-MM-DD แล้วใช้เครื่องมือ `check_calendar` เสมอ
            
            [กฎการวางสาย - สำคัญมาก!]:
            หากการสนทนาจบลงแล้ว หรือผู้โทรบอกลา ให้คุณทำ 2 ขั้นตอนดังนี้:
            1. กล่าวคำบอกลาผู้โทร
            2. ใช้เครื่องมือ `end_call_and_summarize` เพื่อวางสาย โดยคุณต้องส่ง "ข้อความสรุป" (summary) ว่าผู้โทรชื่ออะไร โทรมาเรื่องอะไร และผลลัพธ์คืออะไร เข้าไปในเครื่องมือด้วย""",
        )

    async def on_enter(self) -> None:
        await asyncio.sleep(1)
        await self.session.say("สวัสดีค่ะ ฉันคือผู้ช่วยรับสายแทนคุณจักรพงษ์ มีอะไรให้ช่วยเหลือไหมคะ?")

    # แก้ปัญหา: รับรู้เมื่อผู้โทรพูดแทรก (Barge-in / Interruption)
    async def on_user_started_speaking(self, user) -> None:
        # สั่งให้ AI หยุดพูดประโยคที่ค้างอยู่ทันทีเมื่อคนกำลังพูดแทรก
        self.session.interrupt()
        logging.info("==> 🛑 AI หยุดพูดเพราะจับเสียงผู้โทรพูดแทรกได้ <==")

    async def on_exit(self) -> None:
        await self.session.say("ขอบคุณที่โทรมานะคะ สวัสดีค่ะ")

    # เครื่องมือวางสายและส่งอีเมลสรุป
    @function_tool
    async def end_call_and_summarize(self, summary: str) -> dict:
        """
        Use this tool to end the phone call. You MUST provide a summary of the conversation.
        Args:
            summary: ข้อความสรุปการสนทนาทั้งหมดแบบสั้นๆ กระชับ (ภาษาไทย)
        """
        logging.info(f"==> 🛠️ AI กำลังสรุปข้อมูลเตรียมส่ง Email: {summary} <==")
        
        sender_email = os.getenv("EMAIL_SENDER")
        sender_password = os.getenv("EMAIL_PASSWORD")
        receiver_email = os.getenv("EMAIL_RECEIVER")
        
        if sender_email and sender_password and receiver_email:
            try:
                # สร้างรูปแบบอีเมล
                msg = EmailMessage()
                msg.set_content(f"📞 มีสายเรียกเข้าใหม่!\n\nสรุปการสนทนา:\n{summary}")
                msg['Subject'] = 'แจ้งเตือน: สรุปการโทรจาก AI Assistant'
                msg['From'] = sender_email
                msg['To'] = receiver_email
                
                # เชื่อมต่อและส่งผ่าน Gmail SMTP
                server = smtplib.SMTP('smtp.gmail.com', 587)
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(msg)
                server.quit()
                
                logging.info("==> 📧 ส่งข้อความสรุปเข้า Email สำเร็จ! <==")
            except Exception as e:
                logging.error(f"เกิดข้อผิดพลาดในการส่ง Email: {e}")
        else:
            logging.warning("==> ⚠️ ไม่พบการตั้งค่า Email ในไฟล์ .env <==")

        # สั่งตัดสาย
        asyncio.create_task(self.session.close())
        return {"status": "success", "message": "วางสายและส่งสรุปเข้าอีเมลเรียบร้อย"}

    # 3. อัปเดตฟังก์ชัน check_calendar ให้ดึงข้อมูลจริง
    @function_tool
    async def check_calendar(self, date_str: str) -> dict:
        """
        Check schedule for a specific date. 
        Args:
            date_str: The exact date to check in YYYY-MM-DD format (e.g., '2026-03-12').
        """
        logging.info(f"==> 🛠️ AI กำลังตรวจสอบ Google Calendar สำหรับวันที่: {date_str} <==")
        try:
            service = get_calendar_service()
            
            # คำนวณเวลาเริ่มและจบของวันนั้น
            start_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            # แปลงให้อยู่ใน Timezone ประเทศไทย (UTC+7)
            start_date = start_date.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=7)))
            end_date = start_date + datetime.timedelta(days=1)
            
            events_result = service.events().list(
                calendarId='primary', 
                timeMin=start_date.isoformat(), 
                timeMax=end_date.isoformat(),
                singleEvents=True, 
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])

            if not events:
                return {"status": "success", "message": f"วันที่ {date_str} คุณจักรพงษ์ว่างทั้งวันค่ะ ไม่มีกำหนดการใดๆ"}
            
            # สรุปรายการนัดหมาย
            schedule = []
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                summary = event.get('summary', 'การประชุม')
                schedule.append(f"มีติดธุระเรื่อง {summary}")
            
            schedule_text = ", ".join(schedule)
            return {"status": "success", "message": f"วันที่ {date_str} คุณจักรพงษ์มีกำหนดการดังนี้ค่ะ: {schedule_text}"}

        except Exception as e:
            logging.error(f"Error checking calendar: {e}")
            return {"status": "error", "message": "เกิดข้อผิดพลาด ไม่สามารถดึงข้อมูลปฏิทินได้ในขณะนี้ค่ะ"}

    @function_tool
    async def end_call(self) -> dict:
        """Use this to hang up when conversation is finished."""
        logging.info("==> 🛠️ AI กำลังใช้เครื่องมือ 'end_call' เพื่อวางสาย <==")
        return {"status": "success", "message": "กำลังปิดการสนทนา สนทนาจบลงแล้ว ผู้ใช้จะวางสายเอง"}

async def start_session(context: JobContext):
    model = GeminiRealtime(
        model="gemini-2.5-flash-native-audio-preview-09-2025",
        api_key=os.getenv("GOOGLE_API_KEY"),
        config=GeminiLiveConfig(
            voice="Leda", # เสียง Leda รองรับการพูดภาษาไทยได้เมื่อเราสั่งใน prompt
            response_modalities=["AUDIO"]
        )
    )
    pipeline = RealTimePipeline(model=model)
    session = AgentSession(agent=MyVoiceAgent(), pipeline=pipeline)

    try:
        # Patch แก้บั๊ก _current_utterance_handle ของแพ็กเกจ videosdk 0.0.67
        if not hasattr(pipeline, "_current_utterance_handle"):
            pipeline._current_utterance_handle = None

        await context.connect()
        await session.start()
        await asyncio.Event().wait()
    finally:
        await session.close()
        await context.shutdown()

def make_context() -> JobContext:
    room_options = RoomOptions()
    return JobContext(room_options=room_options)

if __name__ == "__main__":
    try:
        options = Options(
            agent_id="MyTelephonyAgent",  
            register=True,               
            max_processes=10,            
            host="localhost",
            port=8081,
            )
        job = WorkerJob(entrypoint=start_session, jobctx=make_context, options=options)
        job.start()
    except Exception as e:
        traceback.print_exc()