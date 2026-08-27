# การ Deploy Smart Recycle บน Render

## 1. PostgreSQL

สร้าง PostgreSQL ที่ต้องการใช้งานจริง แล้วนำ Internal Database URL ไปใส่ใน
Environment Variable ชื่อ `DATABASE_URL` ของ Web Service
`smart-recycle-admin` ระบบจะใช้ PostgreSQL อัตโนมัติเมื่อพบตัวแปรนี้ และจะใช้
SQLite เฉพาะตอนพัฒนาในเครื่องเมื่อไม่มี `DATABASE_URL`

ก่อนย้ายฐานข้อมูล ให้สำรองข้อมูล SQLite โดยไม่รวม Token ชั่วคราว:

```powershell
python manage.py dumpdata core `
  --exclude core.apitoken `
  --exclude core.passwordresetcode `
  --exclude core.pushdevice `
  --indent 2 `
  -o sqlite-backup.json
```

หลังตั้ง `DATABASE_URL` และรัน `migrate` บนฐานข้อมูลใหม่แล้ว จึงนำเข้าข้อมูล:

```powershell
python manage.py loaddata sqlite-backup.json
```

ไฟล์สำรองอาจมีข้อมูลผู้ใช้และ API Key hash ห้าม Commit หรือเผยแพร่ไฟล์นี้

## 2. Environment Variables

ตั้งค่าบน Render ก่อน Deploy โค้ด Production:

```text
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=<ให้ Render สร้างค่าลับแบบสุ่ม>
DJANGO_ALLOWED_HOSTS=smart-recycle-admin.onrender.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://smart-recycle-admin.onrender.com
CORS_ALLOWED_ORIGINS=https://smart-recycle-admin.onrender.com
CORS_ALLOWED_ORIGIN_REGEXES=^https?://(localhost|127\.0\.0\.1)(:\d+)?$
DATABASE_URL=<Internal PostgreSQL URL>
FIREBASE_CREDENTIALS=/etc/secrets/firebase-service-account.json
```

เพิ่ม Firebase service account ใน Render Secret Files โดยใช้ชื่อ
`firebase-service-account.json` ห้ามใส่เนื้อหาไฟล์นี้ใน Git

## 3. Render Commands

Build command:

```text
pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate
```

Start command:

```text
gunicorn config.wsgi:application
```

## 4. Android Release Signing

สร้าง Keystore เพียงครั้งเดียวและสำรองไว้ในที่ปลอดภัย:

```powershell
keytool -genkeypair -v `
  -keystore android/smart-recycle-release.jks `
  -keyalg RSA -keysize 2048 -validity 10000 `
  -alias smart_recycle
```

คัดลอก `android/key.properties.example` เป็น `android/key.properties` แล้วกรอก
รหัสผ่านที่ใช้สร้าง Keystore จากนั้นสร้างไฟล์สำหรับติดตั้งหรือ Play Store:

```powershell
flutter build apk --release
flutter build appbundle --release
```

ไฟล์ `key.properties` และ Keystore ถูกตั้งให้ Git ข้ามไว้แล้ว ห้าม Commit
และต้องสำรอง Keystore เพราะหากสูญหายจะไม่สามารถอัปเดตแอปเดิมได้
