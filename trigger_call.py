import requests
import os
from dotenv import load_dotenv

load_dotenv()

def trigger_transfer_call(target_phone_number):
    """
    ฟังก์ชันสำหรับทดสอบเรียก API โอนสาย (Twilio) ใน app.py โดยตรง
    (จำลองสถานการณ์เหมือน AI สั่งโอนสาย)
    """
    print(f"กำลังสั่งโอนสายไปยังเบอร์: {target_phone_number}...")

    # เรียกเข้าหาเซิร์ฟเวอร์ Flask ในเครื่องเราเอง
    url = "http://127.0.0.1:5000/transfer_call" 
    payload = {"phoneNumber": target_phone_number}

    try:
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code in [200, 201, 202]:
            print("✅ สั่งโอนสายสำเร็จ! ระบบกำลังดึงโทรศัพท์เข้า Conference...")
            print("รายละเอียด:", response.json())
        else:
            print(f"❌ เกิดข้อผิดพลาด (Status Code: {response.status_code})")
            print("ข้อความ:", response.text)
            
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดของระบบ: {e}")

if __name__ == "__main__":
    # ใช้เบอร์ปลายทางจาก .env หรือค่า Default
    TARGET_PHONE = os.getenv("TRANSFER_NUMBER")
    trigger_transfer_call(TARGET_PHONE)