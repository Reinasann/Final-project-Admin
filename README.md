# RecycleAdmin – Django Version

ระบบจัดการขยะรีไซเคิล แปลงจาก React → Django + conda

## โครงสร้างโปรเจกต์

```
recycleadmin/
├── environment.yml          ← conda environment
├── manage.py
├── config/                  ← Django project config
│   ├── settings.py
│   └── urls.py
└── core/                    ← แอปหลัก
    ├── dummy_data.py        ← ข้อมูล mock ทั้งหมด
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

### 2. migrate database (สำหรับ session)

```bash
python manage.py migrate
```

### 3. รันเซิร์ฟเวอร์

```bash
python manage.py runserver
```

เปิด http://127.0.0.1:8000/ ในเบราว์เซอร์

## Login

กรอก **อีเมลและรหัสผ่านใดก็ได้** เพื่อเข้าสู่ระบบทดสอบ

## ฟีเจอร์

| หน้า | ฟีเจอร์ |
|------|---------|
| Dashboard | สถิติภาพรวม, bar chart แนวโน้มขยะ |
| จัดการเครื่อง | เพิ่ม/แก้ไข, ค้นหา/กรองสถานะ, modal รายละเอียด |
| จัดการสมาชิก | อนุมัติ/ปฏิเสธ pending, ระงับ, เปลี่ยน role |
| แจ้งปัญหา | workflow Waiting→In Progress→Completed, จัดการหัวข้อ |
| รายงาน | กรองตามวันที่/ค้นหา, print |

## หมายเหตุ

- ข้อมูลถูกเก็บใน **Django session** (cookie-based) → รีเฟรชหน้าข้อมูลยังคงอยู่
- Session หมดอายุหลัง 24 ชั่วโมง หรือกด "ออกจากระบบ"
- ใช้ Tailwind CSS CDN + Lucide Icons CDN (ไม่ต้องติดตั้งเพิ่ม)
