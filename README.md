# RecycleAdmin – Django Version

ระบบจัดการขยะรีไซเคิลด้วย Django, SQLite สำหรับพัฒนาในเครื่อง และ PostgreSQL
สำหรับ Production รวม API สำหรับ Flutter, ESP32 และ Firebase Cloud Messaging

## โครงสร้างโปรเจกต์

```
recycleadmin/
├── environment.yml          ← conda environment
├── manage.py
├── config/                  ← Django project config
│   ├── settings.py
│   └── urls.py
└── core/                    ← แอปหลัก
    ├── dummy_data.py        ← ตัวแปลงข้อมูลจากฐานข้อมูลให้เข้ากับ Template เดิม
    ├── views.py             ← logic ทุกหน้า
    ├── urls.py
    ├── templatetags/
    │   └── core_extras.py
    └── templates/core/
        ├── base.html        ← sidebar layout
        ├── login.html
        ├── dashboard.html
        ├── machines.html
        ├── users.html
        ├── issues.html
        └── statistics.html
```

## วิธีติดตั้งและรัน

### 1. สร้าง conda environment

```bash
conda env create -f environment.yml
conda activate recycleadmin
```

### 2. migrate database

```bash
python manage.py migrate
```

### 3. รันเซิร์ฟเวอร์

```bash
python manage.py runserver
```

เปิด http://127.0.0.1:8000/ ในเบราว์เซอร์

## ฐานข้อมูล Production

เมื่อกำหนด `DATABASE_URL` ระบบจะใช้ PostgreSQL อัตโนมัติ ดูขั้นตอนทั้งหมดใน
`DEPLOYMENT.md` ก่อน Deploy ขึ้น Render

## ฟีเจอร์

| หน้า | ฟีเจอร์ |
|------|---------|
| Dashboard | สถิติภาพรวม, bar chart แนวโน้มขยะ |
| จัดการเครื่อง | เพิ่ม/แก้ไข, ค้นหา/กรองสถานะ, modal รายละเอียด |
| จัดการสมาชิก | อนุมัติ/ปฏิเสธ pending, ระงับ, เปลี่ยน role |
| แจ้งปัญหา | workflow Waiting→In Progress→Completed, จัดการหัวข้อ |
| รายงาน | กรองตามวันที่/ค้นหา, print |

## หมายเหตุ

- ข้อมูลระบบทั้งหมดอ่านและบันทึกผ่าน Django ORM
- Admin Session หมดอายุหลัง 24 ชั่วโมง หรือเมื่อกดออกจากระบบ
- Tailwind CSS ถูก Build ไว้ใน Django Static; ใช้ `npm run build:css` หลังเพิ่ม class ใหม่
"# Final-project" 
