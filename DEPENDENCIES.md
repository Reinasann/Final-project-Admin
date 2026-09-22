# โปรแกรมและส่วนเสริมที่ต้องติดตั้ง — Django

ไฟล์นี้อธิบาย dependencies ของระบบผู้ดูแลและ API ส่วนเวอร์ชันที่ติดตั้งจริงควบคุมด้วย
`requirements.txt`, `environment.yml`, `package.json` และ `package-lock.json`

## โปรแกรมหลัก

| โปรแกรม | จำเป็นเมื่อ | หมายเหตุ |
| --- | --- | --- |
| Python 3.11+ | ทุกสภาพแวดล้อม | ใช้รัน Django และคำสั่งจัดการฐานข้อมูล |
| pip หรือ Conda | ติดตั้ง Python packages | เลือกอย่างใดอย่างหนึ่ง |
| PostgreSQL | Production | Render เป็นผู้ดูแลฐานข้อมูลให้ ไม่ต้องติดตั้งบน Web Service |
| Node.js + npm | แก้ไข CSS หน้า Admin | ไม่จำเป็นถ้าใช้ CSS ที่ build ไว้แล้ว |
| Git | Clone, Commit และ Deploy | Render ดึงโค้ดจาก Git repository |

## Python packages

ติดตั้งทั้งหมดด้วย:

```powershell
pip install -r requirements.txt
```

| Package | เวอร์ชัน | หน้าที่ |
| --- | --- | --- |
| Django | `>=5.2,<5.3` | Web framework, ORM, migrations และ session |
| WhiteNoise | `6.6` | ให้ Gunicorn ส่ง static files ใน Production |
| dj-database-url | `>=2.2,<3.0` | อ่าน PostgreSQL URL จาก `DATABASE_URL` |
| psycopg binary | `>=3.2,<4.0` | PostgreSQL driver |
| firebase-admin | `>=7.0,<8.0` | ส่ง Push Notification ผ่าน Firebase Admin SDK |
| Gunicorn | `>=23.0,<27.0` | WSGI server สำหรับ Render |

## Frontend Admin

ติดตั้งเมื่อแก้ Tailwind CSS:

```powershell
npm install
npm run build:css
```

| Package | เวอร์ชัน | หน้าที่ |
| --- | --- | --- |
| Tailwind CSS | `3.4.17` | สร้าง `core/static/core/css/tailwind.css` |

หน้าเว็บโหลดไลบรารีต่อไปนี้จาก CDN จึงต้องมีอินเทอร์เน็ตในเบราว์เซอร์:

- Lucide Icons
- Chart.js
- Leaflet และ OpenStreetMap tiles

## บริการภายนอก

### Render PostgreSQL

ตั้ง `DATABASE_URL` เป็น Internal Database URL ของ PostgreSQL ที่อยู่บัญชีและ region เดียวกับ
Web Service

### Firebase Cloud Messaging

ต้องมี Firebase service-account JSON สำหรับฝั่ง Django และตั้ง:

```text
FIREBASE_CREDENTIALS=/etc/secrets/firebase-service-account.json
```

บน Render ให้อัปโหลดเป็น Secret File ห้าม Commit ไฟล์ credential ลง Git

## ESP32 และ Arduino IDE

เฟิร์มแวร์ส่วนเชื่อม API อยู่ใน `firmware/SmartRecycleController/` และต้องติดตั้ง Library ผ่าน
Arduino IDE Library Manager ดังนี้

| Library | เวอร์ชันแนะนำ | หน้าที่ |
| --- | --- | --- |
| WiFiManager by tzapu | `2.0.17+` | ตั้งค่า Wi-Fi, Serial Number และ Device API Key ผ่าน Captive Portal |
| ArduinoJson by Benoit Blanchon | `7.x` | สร้างและอ่าน JSON ของ Telemetry/Command |
| Adafruit PWM Servo Driver Library | รุ่นล่าสุดที่รองรับบอร์ด | ควบคุม PCA9685 |
| HX711_ADC | รุ่นล่าสุดที่รองรับบอร์ด | อ่านและ Tare Load Cell |

เลือกบอร์ด ESP32 ที่ตรงกับฮาร์ดแวร์จริง และติดตั้ง ESP32 board package ใน Arduino IDE
ก่อน Compile/Upload

## ตรวจสอบหลังติดตั้ง

```powershell
python --version
pip check
python manage.py check
python manage.py test
```
