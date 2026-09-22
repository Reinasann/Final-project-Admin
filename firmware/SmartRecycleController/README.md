# การเชื่อม ESP32 กับ Smart Recycle API

โฟลเดอร์นี้เป็นสเก็ตช์ที่รวมโค้ดคัดแยกเดิมกับระบบ Wi-Fi/API แล้ว ประกอบด้วย:

- `SmartRecycleController.ino` — เซนเซอร์ การจำแนกขยะ Load Cell Ultrasonic Servo และ Stepper
- `SmartRecycleCloud.ino` — WiFiManager การส่ง Telemetry และการรับคำสั่งจาก Django

ต้องเก็บทั้งสองไฟล์ไว้ในโฟลเดอร์ `SmartRecycleController` เดียวกัน Arduino IDE จะคอมไพล์สองแท็บนี้รวมกันอัตโนมัติ

## สิ่งที่ต้องเตรียมใน Django ก่อนทดสอบ

การส่ง Telemetry ใช้ Production URL ที่กำหนดไว้ใน `SmartRecycleCloud.ino` คือ
`https://smart-recycle-admin.onrender.com` ดังนั้นต้องทำสิ่งต่อไปนี้ก่อน:

1. Commit และ Push Django รุ่นที่มี migration `0015_machinecommand`
2. รอ Render Deploy และรัน `python manage.py migrate` สำเร็จ
3. เตรียม Serial Number ในหน้าจัดการเครื่อง
4. เก็บ Device API Key ตอนสร้างหรือสร้าง Key ใหม่ เพราะฐานข้อมูลเก็บเฉพาะค่า Hash และเปิดดู Key เดิมไม่ได้

หากต้องการทดสอบกับ Django ในคอมพิวเตอร์ ต้องเปลี่ยน `API_BASE_URL` ใน
`SmartRecycleCloud.ino` เป็น IP ของคอมพิวเตอร์ที่ ESP32 เข้าถึงได้ ห้ามใช้ `localhost`
หรือ `10.0.2.2` กับ ESP32 จริง

- ใช้ WiFiManager สร้างเครือข่าย `SmartRecycle-Setup` เมื่อตั้งค่าครั้งแรก
- รับ Serial Number และ Device API Key ผ่านหน้า Captive Portal
- ส่งน้ำหนักและระดับขยะทุก 60 วินาทีขณะที่เครื่องทำงาน
- ดึงคำสั่ง `START`, `STOP` และ `RESET_BIN` ทุก 2 วินาที
- ส่งผลตอบรับคำสั่งกลับ Django เพื่อป้องกันคำสั่งสูญหาย
- เมื่อ `START` จะหมุน CH1, CH2 และ CH3 ไปทางซ้ายช่องละ 1 วินาที แล้วจึงให้โค้ดเดิมปิดประตูหลัก
- เมื่อบันทึกการเก็บขยะ ระบบจะ Tare เฉพาะ Load Cell ของถังที่เลือก

## 1. ติดตั้งบอร์ด ESP32 ใน Arduino IDE

1. เปิด Arduino IDE
2. ไปที่ **File > Preferences**
3. ใส่ URL นี้ใน **Additional Boards Manager URLs**:

```text
https://espressif.github.io/arduino-esp32/package_esp32_index.json
```

4. ไปที่ **Tools > Board > Boards Manager**
5. ค้นหา `esp32` และติดตั้ง **esp32 by Espressif Systems**

## 2. ติดตั้ง Library

ไปที่ **Sketch > Include Library > Manage Libraries** แล้วติดตั้ง:

1. `WiFiManager` โดย tzapu รุ่น 2.0.17 ขึ้นไป
2. `ArduinoJson` โดย Benoit Blanchon รุ่น 7.x
3. `Adafruit PWM Servo Driver Library` โดย Adafruit
4. `HX711_ADC` โดย Olav Kallhovd

## 3. เปิดและตรวจสอบโค้ด

1. คัดลอกทั้งโฟลเดอร์ `SmartRecycleController` ไปไว้ในโฟลเดอร์ Arduino sketchbook
2. เปิดไฟล์ `SmartRecycleController.ino` ด้วย Arduino IDE
3. ตรวจว่าด้านบนของ Arduino IDE มีอย่างน้อย 2 แท็บ คือ `SmartRecycleController` และ `SmartRecycleCloud`
4. ไม่ต้องนำสองไฟล์มาต่อกันเอง

## 4. ตั้งค่าบอร์ดและอัปโหลด

1. ต่อ ESP32 กับคอมพิวเตอร์ด้วยสาย USB ที่ส่งข้อมูลได้
2. ไปที่ **Tools > Board > ESP32 Arduino > ESP32 Dev Module** หรือเลือกรุ่นที่ตรงกับบอร์ดจริง
3. ไปที่ **Tools > Port** แล้วเลือก COM ของ ESP32
4. ตั้ง **Upload Speed** เป็น `115200` ก่อน หากใช้งานได้ค่อยเพิ่มความเร็วภายหลัง
5. กด **Verify** เพื่อ Compile
6. หาก Compile ผ่าน กด **Upload**
7. ถ้าหน้าจอขึ้น `Connecting...` ค้าง ให้กดปุ่ม **BOOT** บน ESP32 ค้างไว้จนเริ่มอัปโหลด แล้วปล่อย
8. หลัง Upload เสร็จ เปิด **Tools > Serial Monitor** และตั้ง Baud rate เป็น `115200`

หากขึ้นข้อผิดพลาด `Failed to connect to ESP32` ให้ตรวจสาย USB, เลือก COM ใหม่ และลองกด
BOOT ค้างระหว่างเริ่ม Upload หากไม่พบ COM เลยอาจต้องติดตั้งไดรเวอร์ USB ของบอร์ด เช่น
CP210x หรือ CH340 ตามชิปที่ติดตั้งบนบอร์ด

## 5. การตั้งค่าครั้งแรกผ่าน WiFiManager

1. เปิด ESP32 แล้วเชื่อมโทรศัพท์กับ Wi-Fi `SmartRecycle-Setup`
2. รหัสผ่าน Wi-Fi คือ `smartrecycle`
3. หากหน้าไม่เปิดเอง ให้เข้า `http://192.168.4.1`
4. เลือก Wi-Fi ที่ต้องการใช้งาน
5. ใส่ Serial Number ให้ตรงกับ Django เช่น `ESP32-SR-001`
6. ใส่ Device API Key ที่สร้างไว้ในหน้าจัดการเครื่อง
7. กดบันทึก จากนั้น ESP32 จะจำค่าไว้ในหน่วยความจำถาวร

หากต้องการเปลี่ยน Wi-Fi, Serial Number หรือ Device API Key:

1. หยุดเครื่องก่อน
2. เปิด Serial Monitor ที่ `115200`
3. ส่งตัวอักษร `w`
4. ESP32 จะล้างค่าและรีสตาร์ตกลับเข้าสู่ `SmartRecycle-Setup`

> น้ำหนักจากโค้ดเดิมเป็นกรัม ไฟล์นี้จึงหาร 1,000 ก่อนส่งเป็น `weight_kg` ไปยัง API

## 6. การควบคุมและตรวจสอบ

- ส่ง `s` ใน Serial Monitor เพื่อเปิด/หยุดเครื่องด้วยตัวเอง
- เมื่อสั่ง START ระบบจะปิดประตูคัดแยก CH1–CH3 ก่อน แล้วจึงปิดประตูหลัก
- เมื่อสั่ง STOP มอเตอร์ Servo และสัญญาณ Stepper จะหยุด
- คำสั่งเก็บขยะจากแอปจะ Tare เฉพาะถังที่เลือก
- Serial Monitor จะแสดง `Telemetry -> HTTP 201` เมื่อบันทึกข้อมูลสำเร็จ
- Serial Monitor จะแสดง `Command ACK ... -> HTTP 200` เมื่อทำคำสั่งสำเร็จ

## 7. API ที่อุปกรณ์ใช้งาน

- `POST /api/v1/iot/telemetry/` ส่งค่าถัง
- `GET /api/v1/iot/commands/?device_id=...` ดึงคำสั่งล่าสุด
- `POST /api/v1/iot/commands/{id}/ack/` ตอบรับผลคำสั่ง

ทุก API ต้องส่ง Header `X-Device-Key` และใช้ Serial Number ที่ตรงกับเครื่องในฐานข้อมูล
