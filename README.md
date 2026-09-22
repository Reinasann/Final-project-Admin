# Smart Recycle — Django API และระบบผู้ดูแล

Backend และเว็บผู้ดูแลสำหรับระบบเครื่องคัดแยกขยะอัจฉริยะ รองรับผู้ดูแลระบบสูงสุด
ผู้ดูแลหน่วยงาน ผู้เก็บขยะ แอป Flutter และอุปกรณ์ ESP32

ระบบใช้ Django ORM กับ SQLite สำหรับพัฒนาในเครื่อง และ PostgreSQL สำหรับ Production
ข้อมูลจาก ESP32 จะถูกส่งผ่าน REST API ทุกนาที โดย ESP32 เป็นผู้คำนวณน้ำหนักและระดับขยะ
ก่อนส่งมายังเซิร์ฟเวอร์

## ความสามารถหลัก

- Dashboard สรุปข้อมูลจริงจากฐานข้อมูล พร้อมกราฟแนวโน้มและสัดส่วนขยะ
- จัดการหน่วยงาน ผู้ใช้งาน สิทธิ์ และสถานะบัญชี
- จัดการเครื่อง Serial Number, API Key, สถานะ และพิกัดบนแผนที่
- รับ Telemetry จาก ESP32 สำหรับพลาสติก แก้ว และกระป๋อง
- แจ้งเตือนถังเต็มไปยังผู้ใช้ทุกคนในหน่วยงานผ่าน Firebase Cloud Messaging
- ระบบตอบรับการแจ้งเตือนและแจ้งชื่อผู้ตอบรับให้สมาชิกคนอื่นทราบ
- รายงานปัญหา Waiting → In Progress → Completed
- ส่งข้อมูลให้ Flutter ผ่าน API แบบ Bearer Token
- Session ของ Flutter คงอยู่จนกว่าผู้ใช้จะออกจากระบบ บัญชีถูกระงับ หรือ token ถูกเพิกถอน
- หน้า Admin ใช้ AJAX และรีเฟรชเฉพาะส่วนข้อมูลที่เปลี่ยน

## โครงสร้างสำคัญ

```text
recycleadmin/
├── config/                    การตั้งค่า Django และ URL หลัก
├── core/
│   ├── api.py                 API สำหรับ Flutter และ ESP32
│   ├── models.py              โมเดลฐานข้อมูล
│   ├── views.py               หน้าเว็บผู้ดูแล
│   ├── push.py                ส่ง Firebase Cloud Messaging
│   ├── migrations/            Django migrations
│   ├── templates/core/        HTML ของระบบผู้ดูแล
│   ├── static/core/           CSS และรูปภาพ
│   ├── API.md                 รายละเอียด API
│   └── tests.py               ชุดทดสอบ
├── assets/                    Tailwind CSS input
├── firmware/SmartRecycleController/
│   ├── SmartRecycleCloud.ino  WiFiManager, Telemetry และคิวคำสั่ง ESP32
│   └── README.md              วิธีรวมกับโค้ดเครื่องคัดแยกเดิม
├── DEPENDENCIES.md            รายการโปรแกรมและส่วนเสริม
├── DEPLOYMENT.md              ขั้นตอน Deploy บน Render
├── requirements.txt           Python packages
├── package.json               Tailwind CSS
└── manage.py
```

## ติดตั้งสำหรับพัฒนาในเครื่อง

ต้องมี Python 3.11 ขึ้นไป รายละเอียดทั้งหมดดูที่ [DEPENDENCIES.md](DEPENDENCIES.md)

### 1. สร้าง Virtual Environment

```powershell
cd D:\Project\recycleadmin_django\recycleadmin
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

หรือใช้ Conda:

```powershell
conda env create -f environment.yml
conda activate recycleadmin
```

### 2. เตรียมฐานข้อมูล

หากไม่กำหนด `DATABASE_URL` ระบบจะใช้ `db.sqlite3` สำหรับพัฒนาในเครื่อง

```powershell
python manage.py migrate
```

เพิ่มข้อมูลตัวอย่างเฉพาะเมื่อต้องการ:

```powershell
python manage.py seed_demo_data
```

### 3. Build Tailwind CSS

ไฟล์ CSS ที่ build แล้วอยู่ใน Git จึงไม่จำเป็นต้องติดตั้ง Node.js หากไม่ได้แก้หน้าเว็บ
แต่ถ้าแก้ class หรือ CSS ให้รัน:

```powershell
npm install
npm run build:css
```

### 4. รันเซิร์ฟเวอร์

```powershell
python manage.py runserver 0.0.0.0:8000
```

- เว็บผู้ดูแล: <http://127.0.0.1:8000/>
- API: <http://127.0.0.1:8000/api/v1/>

## Environment Variables

ไฟล์ `.env.example` เป็นรายการตัวแปรอ้างอิง โปรเจกต์อ่านค่าจาก Environment ของระบบโดยตรง
และไม่ได้โหลดไฟล์ `.env` อัตโนมัติ

| ตัวแปร | ใช้งาน |
| --- | --- |
| `DJANGO_DEBUG` | `true` สำหรับพัฒนา และ `false` สำหรับ Production |
| `DJANGO_SECRET_KEY` | ค่าลับของ Django ต้องกำหนดบน Production |
| `DJANGO_ALLOWED_HOSTS` | รายชื่อ host คั่นด้วย comma |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | HTTPS origin ที่เชื่อถือ |
| `CORS_ALLOWED_ORIGINS` | Origin ที่เรียก API ได้ |
| `CORS_ALLOWED_ORIGIN_REGEXES` | รูปแบบ Origin สำหรับ Flutter Web ในเครื่อง |
| `DATABASE_URL` | PostgreSQL connection URL; เว้นว่างเพื่อใช้ SQLite |
| `SQLITE_PATH` | ตำแหน่ง SQLite แบบกำหนดเอง |
| `FIREBASE_CREDENTIALS` | absolute path ของ Firebase service-account JSON |
| `EMAIL_*` | การตั้งค่า SMTP สำหรับลืมรหัสผ่าน |

ตัวอย่างตั้งค่าเฉพาะ PowerShell session:

```powershell
$env:DJANGO_DEBUG = "true"
$env:DJANGO_ALLOWED_HOSTS = "127.0.0.1,localhost"
python manage.py runserver
```

## ฐานข้อมูล

- Development: SQLite เมื่อไม่มี `DATABASE_URL`
- Production: PostgreSQL ผ่าน `DATABASE_URL`
- ห้ามใช้งาน SQLite บน Render แบบไม่มี Persistent Disk เพราะข้อมูลอาจหายหลัง Deploy
- ต้องสำรองและตรวจจำนวนข้อมูลก่อนลบ `db.sqlite3`

ขั้นตอน Render และย้ายข้อมูลอยู่ใน [DEPLOYMENT.md](DEPLOYMENT.md)

## API และ ESP32

รายละเอียด endpoint, header และตัวอย่าง JSON อยู่ใน [core/API.md](core/API.md)

ESP32 ใช้ endpoint:

```text
POST /api/v1/iot/telemetry/
GET  /api/v1/iot/commands/?device_id=<Serial Number>
POST /api/v1/iot/commands/<Command ID>/ack/
Content-Type: application/json
X-Device-Key: <API Key ของ Serial Number นั้น>
```

`device_id` ใน JSON ต้องตรงกับ Serial Number ที่เตรียมไว้ และ `X-Device-Key` ต้องตรงกับ
API Key ของอุปกรณ์ ไม่ควรฝัง API Key จริงใน Git หรือเอกสารสาธารณะ

โค้ด WiFiManager และขั้นตอนรวมเข้ากับสเก็ตช์เดิมอยู่ที่
[firmware/SmartRecycleController/README.md](firmware/SmartRecycleController/README.md)

## ทดสอบ

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

## Deploy

Production ปัจจุบันใช้ Render และ PostgreSQL ดูค่าที่ต้องตั้งและคำสั่ง Deploy ที่
[DEPLOYMENT.md](DEPLOYMENT.md)

ห้าม Commit ไฟล์ต่อไปนี้:

- `db.sqlite3`
- Firebase service-account JSON
- `.env` ที่มีค่าจริง
- ไฟล์สำรองฐานข้อมูล
- API Key แบบข้อความจริง
