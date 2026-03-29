# 🎙️ AI Personal Call Assistant System (PCAS)

โปรเจกต์ **AI Personal Call Assistant System** คือระบบผู้ช่วยรับสายอัจฉริยะที่ช่วยรับสายแทนคุณ โดยสามารถพูดคุยโต้ตอบเป็นภาษาไทยแบบเรียลไทม์ผ่านเว็บเบราว์เซอร์และโอนสายไปยังโทรศัพท์มือถือผ่านเครือข่าย Twilio ได้อย่างสมบูรณ์

---

## 🌟 ฟีเจอร์หลัก (Key Features)

-   **🤖 AI Voice Interaction:** สนทนาตอบโต้ภาษาไทยผ่าน Google Gemini 2.5 Flash (Realtime API) พร้อมรองรับการพูดแทรก (Barge-in)
-   **📞 Smart Call Transfer:** AI สามารถโอนสายจากหน้าเว็บไปยังเบอร์โทรศัพท์มือถือที่กำหนดผ่าน **Twilio Conference** โดยอัตโนมัติ
-   **📅 Google Calendar Integration:** AI สามารถตรวจสอบตารางเวลาและสร้างนัดหมายใหม่ลงใน Google Calendar ได้ทันที
-   **🛡️ Scammer Detection:** ระบบดักจับมิจฉาชีพ AI จะวิเคราะห์บทสนทนาและตัดสายพร้อมส่งอีเมลแจ้งเตือนหากพบพฤติกรรมน่าสงสัย
-   **📧 Auto Summary & Email:** เมื่อจบการสนทนา ระบบจะสรุปประเด็นสำคัญและส่งเข้า Email เจ้าของระบบอัตโนมัติ
-   **🌐 Web Dashboard:** หน้าเว็บสำหรับเริ่มการสนทนากับ AI และแสดงสถานะการโอนสายแบบ Real-time

---

## 🏗️ โครงสร้างโปรเจกต์ (Project Structure)

-   **`app.py`**: เซิร์ฟเวอร์หลัก (Flask) จัดการหน้าเว็บ, ระบบโอนสาย Twilio และการจัดการห้องสนทนา
-   **`main.py`**: ตัวตนของ AI Agent จัดการการรับส่งข้อมูลเสียง, การทำงานร่วมกับ Gemini และเครื่องมือต่างๆ (Tools)
-   **`trigger_call.py`**: สคริปต์สำหรับทดสอบการโอนสายผ่าน API ของระบบ
-   **`.env`**: ไฟล์รวมการตั้งค่า API Key และ Token ทั้งหมด

---

## 📋 สิ่งที่ต้องเตรียม (Prerequisites)

1.  **VideoSDK Account**: สำหรับสร้างห้องสนทนาและเชื่อมต่อ AI
2.  **Google AI Studio API Key**: สำหรับใช้งาน Gemini 2.5 Flash
3.  **Google Cloud Console**:
    -   เปิดใช้งาน **Google Calendar API**
    -   สร้าง **OAuth 2.0 Credentials** (ดาวน์โหลดไฟล์ `credentials.json`)
4.  **Twilio Account**:
    -   Account SID, Auth Token และ Twilio Phone Number
5.  **Gmail Account**: สำหรับส่งอีเมลสรุป (ต้องสร้าง **App Password**)

---

## 🚀 การติดตั้งและเริ่มใช้งาน (Get Started)

### 1. ติดตั้ง Dependencies
```bash
pip install -r requirements.txt
```

### 2. ตั้งค่าไฟล์ `.env`
สร้างไฟล์ `.env` และกรอกข้อมูลของคุณ:
```env
# VideoSDK
VIDEOSDK_TOKEN="your_videosdk_token"

# Google Gemini
GOOGLE_API_KEY="your_gemini_api_key"

# Email Configuration
EMAIL_SENDER="your_sender@gmail.com"
EMAIL_PASSWORD="your_app_password"
EMAIL_RECEIVER="your_receiver@gmail.com"

# Twilio Configuration
TWILIO_ACCOUNT_SID="your_sid"
TWILIO_AUTH_TOKEN="your_token"
TWILIO_PHONE_NUMBER="your_twilio_number"

# User Profile
USER_NAME="ชื่อของคุณ"
TRANSFER_NUMBER="เบอร์โทรศัพท์ของคุณ"
```

### 3. ตั้งค่า Google Calendar
-   วางไฟล์ `credentials.json` ไว้ในโฟลเดอร์โปรเจกต์
-   รัน `python main.py` ครั้งแรกเพื่อทำการ Login (ไฟล์ `token.json` จะถูกสร้างขึ้นอัตโนมัติ)

### 4. รันระบบ
เปิด Terminal แล้วรันเซิร์ฟเวอร์หลัก:
```bash
python app.py
```
*(ถ้าต้องการให้โทรศัพท์โอนสายได้ ต้องรัน ngrok ก่อน: `ngrok http 5000`)*

---

## 🛠️ วิธีการใช้งาน
1.  เปิดหน้าเว็บที่ `http://localhost:5000`
2.  กดปุ่ม **"เชื่อมต่อสาย AI ทันที"**
3.  เริ่มพูดคุยกับ AI ได้ทันที
4.  หากต้องการโอนสาย ให้พูดว่า **"ขอสายคุณ[ชื่อของคุณ]"** AI จะดึงเบอร์โทรศัพท์ของคุณเข้ามาร่วมสนทนาในทันที!

---

## ⚖️ ข้อกำหนดด้านความปลอดภัย (Disclaimer)
โปรเจกต์นี้ใช้เทคโนโลยี AI และการเข้าถึงข้อมูลส่วนตัว (Calendar/Email) โปรดระมัดระวังการเปิดเผย API Key ของคุณในที่สาธารณะ
