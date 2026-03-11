# AI Voice Assistant (VideoSDK + Gemini)

โปรเจกต์นี้เป็นระบบ **AI Voice Assistant** ที่สามารถรับสายและพูดคุยโต้ตอบเป็นภาษาไทยได้แบบเรียลไทม์ โดยใช้เทคโนโลยีจาก **VideoSDK** และ **Google Gemini 2.5 Flash Realtime API**

AI ถูกออกแบบมาให้ทำหน้าที่เป็นผู้ช่วยรับสายแทน 
มีความสามารถในการรับฟังคำสั่ง จัดการการพูดแทรก (Barge-in) ตรวจสอบตารางนัดหมายผ่าน Google Calendar และเมื่อวางสาย ระบบจะทำการสรุปการสนทนาและส่งแจ้งเตือนผ่าน Email โดยอัตโนมัติ

---

## 🌟 ฟีเจอร์หลัก (Key Features)

- **สนทนาภาษาไทยแบบเรียลไทม์:** โต้ตอบได้อย่างเป็นธรรมชาติและเป็นมิตร
- **รองรับการพูดแทรก (Barge-in / Interruption):** AI จะหยุดพูดและรับฟังทันทีหากผู้โทรพูดแทรก
- **เชื่อมต่อ Google Calendar:** สามารถตรวจสอบตารางเวลาและนัดหมายของคุณจักรพงษ์ได้แบบอัปเดตล่าสุด
- **สรุปและส่งอีเมลแจ้งเตือน:** เมื่อจบการสนทนา AI จะสรุปประเด็นสำคัญและส่งเข้า Email ทันที
- **ระบบโทรออกอัตโนมัติ (Outbound Call):** รองรับการสั่งให้ AI โทรออกไปยังเบอร์โทรศัพท์ที่ต้องการผ่าน SIP ของ VideoSDK

---

## 📋 สิ่งที่ต้องเตรียม (Prerequisites)

ก่อนเริ่มใช้งาน ให้ตรวจสอบว่าคุณมีสิ่งเหล่านี้ครบถ้วน:

1. **Python 3.9+** ติดตั้งในเครื่อง
2. **VideoSDK Account**: ไปที่ [VideoSDK](https://www.videosdk.live/) เพื่อสมัครและรับ API Token (เลือกใช้ SIP/Telephony)
3. **Google Cloud Console**:
   - เปิดใช้งาน **Gemini API** สำหรับรับส่งข้อมูลแบบ Realtime เสียง
   - เปิดใช้งาน **Google Calendar API**
   - สร้างและดาวน์โหลด **OAuth 2.0 Client IDs** (ไฟล์ `credentials.json`)
4. **Gmail Account**:
   - เปิดใช้งาน 2-Step Verification
   - สร้าง **App Password** สำหรับส่งอีเมลผ่าน SMTP

---

## 🛠️ การติดตั้ง (Installation)

1. **Clone Repository (หรือเปิดโฟลเดอร์โปรเจกต์)**
   เข้าสู่ไดเรกทอรีของโปรเจกต์

2. **สร้าง Virtual Environment (แนะนำ)**
   เพื่อแยกแพ็คเกจไม่ให้ปะปนกับระบบหลัก
   ```bash
   # Windows
   python -m venv venv
   .\venv\Scripts\activate

   # macOS / Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **ติดตั้ง Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

---

## ⚙️ การตั้งค่าระบบ (Configuration)

### 1. ตั้งค่า Environment Variables (`.env`)
สร้างไฟล์ชื่อ `.env` ในโฟลเดอร์รันไทม์และกำหนดค่าตามนี้:

```env
# ตั้งค่า VideoSDK
VIDEO_SDK_TOKEN=your_videosdk_token_here

# ตั้งค่า Google Gemini API
GOOGLE_API_KEY=your_gemini_api_key_here

# ตั้งค่า Email สำหรับส่งและรับแจ้งเตือน
EMAIL_SENDER=your_email@gmail.com
EMAIL_PASSWORD=your_gmail_app_password
EMAIL_RECEIVER=receiver_email@example.com
```

### 2. ตั้งค่า Google Calendar (`credentials.json`)
นำไฟล์ `credentials.json` ที่ดาวน์โหลดมาจาก Google Cloud Console มาวางไว้ในโฟลเดอร์เดียวกับโปรเจกต์ เพื่อใช้ยืนยันสิทธิ์เข้าถึง Calendar
*(หมายเหตุ: ในการรันหน้าต่างเข้าสู่ระบบครั้งแรก ระบบจะสร้างไฟล์ `token.json` ขึ้นมาเก็บไว้ใช้งานครั้งต่อไปโดยอัตโนมัติ)*

---

## 🚀 การใช้งาน (Usage)

### 1. เริ่มต้นระบบ AI Agent
รันสคริปต์หลักเพื่อเตรียม Agent ให้พร้อมรับสาย:
```bash
python main.py
```
*(ถ้ารันครั้งแรก ระบบจะเปิดเบราว์เซอร์ให้คุณกดล็อกอินบัญชี Google เพื่อให้สิทธิ์อ่าน Calendar)*

เมื่อขึ้น Status ว่าพร้อมทำงาน ระบบจะคอยสแตนด์บายรับสาย (Inbound) ตามที่ตั้งค่า SIP ไว้ใน VideoSDK

### 2. การสั่งให้ AI โทรออก (Outbound Call)
หากต้องการให้ AI เป็นคนโทรออกหาลูกค้าหรือเบอร์ที่กำหนด ให้เปิด Command Promt/Terminal ใหม่อีกหน้าต่าง (ขณะที่ `main.py` ยังรันอยู่) และแก้ไขเบอร์โทรในโปรแกรม `trigger_call.py` จากนั้นรัน:

```bash
python trigger_call.py
```
ระบบจะสั่งการผ่าน API ของ VideoSDK ไปที่โครงข่ายโทรศัพท์ และเมื่อผู้รับสายรับสาย AI จะเริ่มทำงานตามเงื่อนไขที่กำหนดไว้

---

## 📁 โครงสร้างโปรเจกต์ (Project Structure)

- `main.py`: ไฟล์หลัก ทำหน้าที่สร้าง AI Agent, จัดการ Prompt, ตรวจจับการพูดแทรก, เชื่อมต่อ Google Calendar และส่งอีเมลสรุปหลังวางสาย
- `trigger_call.py`: ไฟล์สำหรับส่งคำสั่ง API เพื่อให้ AI โทรออกไปยังเบอร์เป้าหมาย (Outbound Call)
- `requirements.txt`: รายการแพ็คเกจ Python ทั้งหมดที่โปรเจกต์จำเป็นต้องใช้
- `.env`: (ผู้ใช้สร้างเอง) สำหรับเก็บความลับและซ่อน API Key / Token / Password
- `credentials.json` & `token.json`: ไฟล์ยืนยันตัวตนสำหรับ Google Calendar API (OAuth 2.0)
