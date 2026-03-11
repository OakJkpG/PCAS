import requests
import os
from dotenv import load_dotenv

# โหลดค่า Token จากไฟล์ .env
load_dotenv()

def make_outbound_call(target_phone_number):
    """
    ฟังก์ชันสำหรับสั่งให้ AI Agent โทรออกไปยังเบอร์ที่กำหนด
    """
    print(f"กำลังสั่งให้ AI โทรออกไปยังเบอร์: {target_phone_number}...")

    # 1. ใส่ URL เดียวกับที่คุณใช้ใน Postman
    # (โดยปกติจะเป็น https://api.videosdk.live/v2/telephony/outbound-calls หรือตามที่ VideoSDK กำหนด)
    url = "https://api.videosdk.live/v2/sip/call" 

    # 2. เตรียม Headers (สิทธิ์การเข้าถึง)
    # หมายเหตุ: ตรวจสอบให้แน่ใจว่าในไฟล์ .env ของคุณตั้งชื่อตัวแปรเก็บ Token ไว้ว่า VIDEO_SDK_TOKEN หรือชื่ออื่นๆ แล้วแก้ให้ตรงกันครับ
    token = os.getenv("VIDEO_SDK_TOKEN") 
    
    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }

    # 3. เตรียมข้อมูล (Body) แบบเดียวกับที่กรอกใน Postman
    payload = {
        "gatewayId": "",
        "sipCallTo": target_phone_number
    }

    # 4. ยิง Request ผ่าน API
    try:
        response = requests.post(url, headers=headers, json=payload)
        
        # ตรวจสอบผลลัพธ์
        if response.status_code in [200, 201, 202]:
            print("✅ สั่งโทรออกสำเร็จ! ระบบกำลังเชื่อมต่อสาย...")
            print("รายละเอียด:", response.json())
        else:
            print(f"❌ เกิดข้อผิดพลาด (Status Code: {response.status_code})")
            print("ข้อความ:", response.text)
            
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดของระบบ: {e}")

if __name__ == "__main__":
    # ใส่เบอร์โทรศัพท์ปลายทางที่คุณต้องการให้ AI โทรหา (เบอร์มือถือของคุณ)
    # รูปแบบเช่น "+66812345678"
    #PHONE_NUMBER = "+66999412500"
    PHONE_NUMBER = "+66924437639"
    
    

    make_outbound_call(PHONE_NUMBER)
