#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <HX711_ADC.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <WiFiManager.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>

// =====================================================
// PCA9685
// =====================================================
Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(0x40);

// =====================================================
// SERVO CHANNELS
// =====================================================

// CH0 = Servo เคาะ Piezo
#define SERVO_CH 0

// Servo ช่องคัดแยก
#define PLASTIC_SERVO_CH 1
#define METAL_SERVO_CH   2
#define GLASS_SERVO_CH   3

// =====================================================
// CONTINUOUS ROTATION SERVO PWM (PCA9685 @ 50 Hz)
// Servo ทุกตัวเป็นแบบ 360 องศา: ซ้าย / หยุด / ขวา
// =====================================================
#define SERVO_LEFT   205
#define SERVO_STOP   320
#define SERVO_RIGHT  410
#define SERVO_PWM_FREQUENCY 50

// ระยะเวลาหมุน Servo เคาะ Piezo
#define SERVO_TURN_TIME 500

// Servo คัดแยก
// เปิด = RIGHT 1 sec
// ปิด = LEFT 1 sec
#define SORT_SERVO_TIME 1000

// =====================================================
// PHOTO SENSOR
// =====================================================
#define PHOTO_PIN 14

// NPN: 0 = ไม่มีวัตถุ, 1 = มีวัตถุ
#define PHOTO_START_DELAY 2000

// =====================================================
// PIEZO
// =====================================================
#define PIEZO_PIN 32

#define PIEZO_TEST_COUNT 3
#define PIEZO_BETWEEN_HITS 250

// Plastic < 3000
// Glass >= 3000
#define PLASTIC_MAX 2999
#define GLASS_MIN   3000

// =====================================================
// METAL SENSOR
// =====================================================
#define METAL_PIN 33

// 0 = ไม่มีโลหะ
// 1 = มีโลหะ
#define METAL_SAMPLE_COUNT 30
#define METAL_SAMPLE_DELAY 10
#define METAL_CONFIRM_COUNT 5

bool metalLatched = false;

// =====================================================
// INSPECTION LOAD CELL
// =====================================================
#define HX_DOUT 19
#define HX_SCK  18

HX711_ADC LoadCell(HX_DOUT, HX_SCK);

float calibrationValue = 23.50;

// =====================================================
// WEIGHT CLASSIFICATION
// =====================================================
#define LIGHT_WEIGHT_MAX 100.0f
#define HEAVY_WEIGHT_MIN 200.0f
#define MAX_VALID_OBJECT_WEIGHT 2000.0f

// =====================================================
// LOAD CELL STABILITY
// =====================================================
#define STABLE_SAMPLE_COUNT 10
#define STABLE_SPREAD_MAX   5.0f
#define STABLE_TIMEOUT      6000

#define AUTO_ZERO_SETTLE_TIME 1500

// =====================================================
// OBJECT LEAVE
// =====================================================
#define EMPTY_RETURN_TOLERANCE 30.0f
#define EMPTY_CONFIRM_COUNT    10

#define OBJECT_LEAVE_TIMEOUT 10000

// =====================================================
// STEPPER A4988
// =====================================================
#define STEP_PIN 26
#define DIR_PIN  27
#define EN_PIN   25

const int STEPS_PER_REV = 200;
const int STEP_DELAY_US = 1500;

// =====================================================
// DOOR
// =====================================================
// ใช้ทิศทางเดียวกับโค้ดเดิมที่ทดสอบกับเครื่องจริงแล้ว
#define DOOR_OPEN_ANGLE  -4320
#define DOOR_CLOSE_ANGLE  4320

#define DOOR_WAIT_TIME 1000

// =====================================================
// HC-SR04 x3
//
// ECHO ของ HC-SR04 เป็น 5V
// ต้องลดลงเหลือประมาณ 3.3V ก่อนเข้า ESP32
// =====================================================

// ---------------------
// U1
// ---------------------
#define U1_TRIG 4
#define U1_ECHO 39

#define U1_EMPTY_DISTANCE 67.47f
#define U1_FULL_DISTANCE  18.00f

// ---------------------
// U2
// ---------------------
#define U2_TRIG 5
#define U2_ECHO 12

#define U2_EMPTY_DISTANCE 56.72f
#define U2_FULL_DISTANCE   8.00f

// ---------------------
// U3
// ---------------------
#define U3_TRIG 16
#define U3_ECHO 15

#define U3_EMPTY_DISTANCE 67.81f
#define U3_FULL_DISTANCE  20.00f

#define ULTRASONIC_INTERVAL 700
#define ULTRASONIC_TIMEOUT_US 25000UL

// =====================================================
// BIN HX711 x3
// =====================================================

// BIN 1
#define BIN1_DOUT 34
#define BIN1_SCK  17

HX711_ADC BinLoad1(
  BIN1_DOUT,
  BIN1_SCK
);

float binCalibration1 = 21.05;

// BIN 2
#define BIN2_DOUT 35
#define BIN2_SCK  23

HX711_ADC BinLoad2(
  BIN2_DOUT,
  BIN2_SCK
);

float binCalibration2 = 21.90;

// BIN 3
#define BIN3_DOUT 36
#define BIN3_SCK  13

HX711_ADC BinLoad3(
  BIN3_DOUT,
  BIN3_SCK
);

float binCalibration3 = 17.90;

// =====================================================
// BIN DATA
// =====================================================
struct BinData {

  float distance;
  float percent;
  float weight;

  bool distanceValid;
};

BinData bin1;
BinData bin2;
BinData bin3;

// =====================================================
// OBJECT TYPE
// =====================================================
enum ObjectType {

  TYPE_UNKNOWN,
  TYPE_GLASS,
  TYPE_PLASTIC,
  TYPE_METAL
};

// =====================================================
// SENSOR DATA
// =====================================================
struct SensorData {

  int piezo[PIEZO_TEST_COUNT];

  float weight;

  bool weightValid;

  bool metalDetected;

  ObjectType result;
};

// =====================================================
// SYSTEM VARIABLES
// =====================================================
volatile bool systemRunning = false;

// ป้องกันการส่ง Telemetry ก่อนปิดประตูหลักและ Auto Zero เสร็จ
volatile bool cloudMachineReady = false;

bool photoTriggered = false;

bool closeDoorOnStartRequested = false;

// Zero ของ Load Cell จุดตรวจ
float emptyWeight = 0;

// =====================================================
// SORT GATE STATE
//
// -1 = ไม่มีช่องเปิด
// 1  = Plastic
// 2  = Metal
// 3  = Glass
// =====================================================
int lastOpenedServoChannel = -1;

// =====================================================
// BIN MONITOR
// =====================================================
unsigned long lastUltrasonicTime = 0;

int ultrasonicIndex = 0;

bool binStatusReady = false;

// =====================================================
// FORWARD DECLARATIONS
// =====================================================
void serviceBinLoadCells();
void serviceAllLoadCells();
void checkSerial();
void setupCloud();
void serviceCloud();
void resetCloudConfiguration();
bool startMachineFromCloud();
void stopMachineFromCloud();

// =====================================================
// CH0 - PIEZO SERVO
// =====================================================
void leftServo() {

  pwm.setPWM(
    SERVO_CH,
    0,
    SERVO_LEFT
  );
}

void rightServo() {

  pwm.setPWM(
    SERVO_CH,
    0,
    SERVO_RIGHT
  );
}

void stopServo() {

  pwm.setPWM(
    SERVO_CH,
    0,
    SERVO_STOP
  );
}

// =====================================================
// SORT SERVOS CH1 - CH3
// =====================================================
void stopSortServo(
  int channel
) {

  if (
    channel < 1 ||
    channel > 15
  ) {

    return;
  }

  pwm.setPWM(
    channel,
    0,
    SERVO_STOP
  );
}

// =====================================================
// STOP ALL SORT SERVOS
// =====================================================
void stopAllSortServos() {

  stopSortServo(
    PLASTIC_SERVO_CH
  );

  stopSortServo(
    METAL_SERVO_CH
  );

  stopSortServo(
    GLASS_SERVO_CH
  );
}

// =====================================================
// MOVE SORT SERVO
// =====================================================
bool moveSortServo(
  int channel,
  int pwmValue,
  unsigned long duration
) {

  if (
    channel < 1 ||
    channel > 15
  ) {

    return false;
  }

  pwm.setPWM(
    channel,
    0,
    pwmValue
  );

  unsigned long start =
    millis();

  while (
    millis() - start <
    duration
  ) {

    serviceAllLoadCells();

    checkSerial();

    if (!systemRunning) {

      stopSortServo(
        channel
      );

      return false;
    }

    delay(1);
  }

  stopSortServo(
    channel
  );

  return true;
}

// =====================================================
// OPEN SORT GATE
//
// RIGHT 1 SECOND
// =====================================================
bool openSortGate(
  int channel
) {

  Serial.println();
  Serial.println("------------------------------");

  Serial.print(
    "OPEN SORT SERVO CH"
  );

  Serial.println(
    channel
  );

  Serial.println(
    "RIGHT 1 SECOND"
  );

  Serial.println("------------------------------");

  if (
    !moveSortServo(
      channel,
      SERVO_RIGHT,
      SORT_SERVO_TIME
    )
  ) {

    return false;
  }

  // จำช่องที่เปิด
  lastOpenedServoChannel =
    channel;

  Serial.print(
    "SORT SERVO CH"
  );

  Serial.print(
    channel
  );

  Serial.println(
    " = OPEN"
  );

  return true;
}

// =====================================================
// CLOSE PREVIOUS SORT GATE
//
// LEFT 1 SECOND
// =====================================================
bool closePreviousSortGate() {

  // ไม่มีช่องเปิดอยู่
  if (
    lastOpenedServoChannel ==
    -1
  ) {

    Serial.println(
      "No previous sort gate to close"
    );

    return true;
  }

  int channel =
    lastOpenedServoChannel;

  Serial.println();
  Serial.println("------------------------------");

  Serial.print(
    "CLOSE PREVIOUS SERVO CH"
  );

  Serial.println(
    channel
  );

  Serial.println(
    "LEFT 1 SECOND"
  );

  Serial.println("------------------------------");

  if (
    !moveSortServo(
      channel,
      SERVO_LEFT,
      SORT_SERVO_TIME
    )
  ) {

    return false;
  }

  lastOpenedServoChannel =
    -1;

  Serial.print(
    "SORT SERVO CH"
  );

  Serial.print(
    channel
  );

  Serial.println(
    " = CLOSED"
  );

  return true;
}

// =====================================================
// OPEN GATE FROM TYPE
// =====================================================
bool openGateForType(
  ObjectType type
) {

  switch (type) {

    // =================================================
    // PLASTIC -> CH1
    // =================================================
    case TYPE_PLASTIC:

      Serial.println();
      Serial.println(
        "ROUTE -> PLASTIC -> CH1"
      );

      return openSortGate(
        PLASTIC_SERVO_CH
      );

    // =================================================
    // METAL -> CH2
    // =================================================
    case TYPE_METAL:

      Serial.println();
      Serial.println(
        "ROUTE -> METAL -> CH2"
      );

      return openSortGate(
        METAL_SERVO_CH
      );

    // =================================================
    // GLASS -> CH3
    // =================================================
    case TYPE_GLASS:

      Serial.println();
      Serial.println(
        "ROUTE -> GLASS -> CH3"
      );

      return openSortGate(
        GLASS_SERVO_CH
      );

    // =================================================
    // UNKNOWN
    // =================================================
    default:

      Serial.println();
      Serial.println(
        "ROUTE -> UNKNOWN"
      );

      Serial.println(
        "No sorting servo opened"
      );

      return true;
  }
}

// =====================================================
// BIN LOAD CELLS
// =====================================================
void serviceBinLoadCells() {

  // ===================================================
  // BIN 1
  // ===================================================
  if (
    BinLoad1.update()
  ) {

    float w =
      BinLoad1.getData();

    if (
      fabs(w) <
      20.0f
    ) {

      w = 0;
    }

    if (
      w < 0
    ) {

      w = 0;
    }

    bin1.weight =
      w;
  }

  // ===================================================
  // BIN 2
  // ===================================================
  if (
    BinLoad2.update()
  ) {

    float w =
      BinLoad2.getData();

    if (
      fabs(w) <
      20.0f
    ) {

      w = 0;
    }

    if (
      w < 0
    ) {

      w = 0;
    }

    bin2.weight =
      w;
  }

  // ===================================================
  // BIN 3
  // ===================================================
  if (
    BinLoad3.update()
  ) {

    float w =
      BinLoad3.getData();

    if (
      fabs(w) <
      20.0f
    ) {

      w = 0;
    }

    if (
      w < 0
    ) {

      w = 0;
    }

    bin3.weight =
      w;
  }
}

// =====================================================
// SERVICE ALL LOAD CELLS
// =====================================================
void serviceAllLoadCells() {

  LoadCell.update();

  serviceBinLoadCells();
}

// =====================================================
// SERIAL COMMAND
//
// s = Start / Stop
// t = Tare BIN HX711
// =====================================================
void checkSerial() {

  if (
    Serial.available() <= 0
  ) {

    return;
  }

  char command =
    Serial.read();

  // ===================================================
  // START / STOP
  // ===================================================
  if (
    command == 's' ||
    command == 'S'
  ) {

    // Serial และคำสั่งจากแอปใช้ START/STOP ชุดเดียวกัน
    if (systemRunning) {

      stopMachineFromCloud();

    } else if (!startMachineFromCloud()) {

      Serial.println("SYSTEM START FAILED");
    }
  }

  // ===================================================
  // TARE BIN HX711
  // ===================================================
  else if (
    command == 't' ||
    command == 'T'
  ) {

    if (
      !systemRunning
    ) {

      Serial.println();
      Serial.println("================================");
      Serial.println("TARE BIN LOAD CELLS");
      Serial.println("ถังทั้ง 3 ต้องว่าง");
      Serial.println("================================");

      BinLoad1.tareNoDelay();

      BinLoad2.tareNoDelay();

      BinLoad3.tareNoDelay();

    } else {

      Serial.println(
        "STOP ระบบก่อนใช้คำสั่ง t"
      );
    }
  }

  // ===================================================
  // RESET WI-FI + DEVICE CREDENTIALS
  // ===================================================
  else if (
    command == 'w' ||
    command == 'W'
  ) {

    if (!systemRunning) {

      resetCloudConfiguration();
      delay(500);
      ESP.restart();

    } else {

      Serial.println(
        "STOP ระบบก่อนใช้คำสั่ง w"
      );
    }
  }

  // Clear CR/LF
  while (
    Serial.available()
  ) {

    char c =
      Serial.peek();

    if (
      c == '\n' ||
      c == '\r'
    ) {

      Serial.read();

    } else {

      break;
    }
  }
}

// =====================================================
// SMART DELAY
// =====================================================
bool smartDelay(
  unsigned long waitTime
) {

  unsigned long start =
    millis();

  while (
    millis() - start <
    waitTime
  ) {

    serviceAllLoadCells();

    checkSerial();

    if (
      !systemRunning
    ) {

      stopServo();

      stopAllSortServos();

      return false;
    }

    delay(1);
  }

  return true;
}

// =====================================================
// PHOTO SENSOR
// =====================================================
bool detectPhotoTrigger() {

  int state =
    digitalRead(
      PHOTO_PIN
    );

  // ===================================================
  // OBJECT
  // ===================================================
  if (
    state == HIGH &&
    !photoTriggered
  ) {

    photoTriggered =
      true;

    Serial.println();
    Serial.println("================================");
    Serial.println("PHOTO TRIGGER!");
    Serial.println("ตรวจพบวัตถุใหม่");
    Serial.println("================================");

    return true;
  }

  // ===================================================
  // NO OBJECT
  // ===================================================
  if (
    state == LOW
  ) {

    photoTriggered =
      false;
  }

  return false;
}

// =====================================================
// WATCH METAL
// =====================================================
void watchMetal() {

  if (
    digitalRead(
      METAL_PIN
    ) ==
    HIGH
  ) {

    metalLatched =
      true;
  }
}

// =====================================================
// WAIT 2 SECONDS AFTER PHOTO
// =====================================================
bool waitAfterPhotoAndWatchMetal() {

  metalLatched =
    false;

  unsigned long start =
    millis();

  Serial.println();
  Serial.println(
    "รอ 2 วินาทีก่อนเริ่มตรวจ..."
  );

  while (
    millis() - start <
    PHOTO_START_DELAY
  ) {

    serviceAllLoadCells();

    checkSerial();

    if (
      !systemRunning
    ) {

      return false;
    }

    watchMetal();

    delay(2);
  }

  Serial.println();
  Serial.println(
    "ครบ 2 วินาที"
  );

  if (
    metalLatched
  ) {

    Serial.println(
      "Metal detected during wait"
    );
  }

  return true;
}

// =====================================================
// METAL CHECK
// =====================================================
bool detectMetalStable() {

  Serial.println();
  Serial.println("------------------------------");
  Serial.println("METAL SENSOR CHECK");
  Serial.println("------------------------------");

  // ===================================================
  // เคยเจอระหว่างรอแล้ว
  // ===================================================
  if (
    metalLatched
  ) {

    Serial.println(
      "Metal Latched = YES"
    );

    Serial.println(
      "METAL DETECTED"
    );

    return true;
  }

  int highCount = 0;

  for (
    int i = 0;
    i < METAL_SAMPLE_COUNT;
    i++
  ) {

    int state =
      digitalRead(
        METAL_PIN
      );

    if (
      state == HIGH
    ) {

      highCount++;
    }

    serviceAllLoadCells();

    checkSerial();

    if (
      !systemRunning
    ) {

      return false;
    }

    delay(
      METAL_SAMPLE_DELAY
    );
  }

  Serial.print(
    "Metal HIGH Count = "
  );

  Serial.print(
    highCount
  );

  Serial.print("/");

  Serial.println(
    METAL_SAMPLE_COUNT
  );

  if (
    highCount >=
    METAL_CONFIRM_COUNT
  ) {

    Serial.println(
      "METAL DETECTED"
    );

    return true;
  }

  Serial.println(
    "NO METAL"
  );

  return false;
}

// =====================================================
// READ STABLE INSPECTION WEIGHT
// =====================================================
bool readStableWeight(
  float &result
) {

  unsigned long totalStart =
    millis();

  while (
    millis() -
    totalStart <
    STABLE_TIMEOUT
  ) {

    float total = 0;

    float minValue =
      999999.0f;

    float maxValue =
      -999999.0f;

    int count = 0;

    while (
      count <
      STABLE_SAMPLE_COUNT
    ) {

      checkSerial();

      serviceBinLoadCells();

      if (
        !systemRunning
      ) {

        return false;
      }

      if (
        LoadCell.update()
      ) {

        float value =
          LoadCell.getData();

        total +=
          value;

        if (
          value <
          minValue
        ) {

          minValue =
            value;
        }

        if (
          value >
          maxValue
        ) {

          maxValue =
            value;
        }

        count++;
      }

      if (
        millis() -
        totalStart >=
        STABLE_TIMEOUT
      ) {

        return false;
      }
    }

    float average =
      total /
      count;

    float spread =
      maxValue -
      minValue;

    Serial.print(
      "Weight Average = "
    );

    Serial.print(
      average,
      1
    );

    Serial.print(
      " g | Spread = "
    );

    Serial.print(
      spread,
      1
    );

    Serial.println(" g");

    if (
      spread <=
      STABLE_SPREAD_MAX
    ) {

      result =
        average;

      return true;
    }

    if (
      !smartDelay(100)
    ) {

      return false;
    }
  }

  return false;
}

// =====================================================
// AUTO ZERO INSPECTION LOAD CELL
// =====================================================
bool autoZeroLoadCell() {

  Serial.println();
  Serial.println("================================");
  Serial.println("AUTO ZERO LOAD CELL");
  Serial.println("================================");

  if (
    !smartDelay(
      AUTO_ZERO_SETTLE_TIME
    )
  ) {

    return false;
  }

  float newZero = 0;

  if (
    !readStableWeight(
      newZero
    )
  ) {

    Serial.println(
      "AUTO ZERO FAILED"
    );

    Serial.println(
      "KEEP OLD ZERO"
    );

    return true;
  }

  emptyWeight =
    newZero;

  Serial.print(
    "New Zero Raw = "
  );

  Serial.print(
    emptyWeight,
    1
  );

  Serial.println(" g");

  Serial.println(
    "Net Weight = 0.0 g"
  );

  return true;
}

// =====================================================
// PIEZO STRIKE
// =====================================================
int readPiezoStrike() {

  int peak = 0;

  unsigned long start =
    millis();

  unsigned long counter =
    0;

  rightServo();

  while (
    millis() - start <
    SERVO_TURN_TIME
  ) {

    int value =
      analogRead(
        PIEZO_PIN
      );

    if (
      value > peak
    ) {

      peak =
        value;
    }

    counter++;

    if (
      counter % 16 == 0
    ) {

      serviceAllLoadCells();
    }

    if (
      counter % 64 == 0
    ) {

      checkSerial();

      if (
        !systemRunning
      ) {

        stopServo();

        return peak;
      }
    }
  }

  stopServo();

  return peak;
}

// =====================================================
// PIEZO TEST x3
// =====================================================
bool runPiezoTests(
  SensorData &data
) {

  Serial.println();
  Serial.println("================================");
  Serial.println("PIEZO TEST x3");
  Serial.println("================================");

  for (
    int i = 0;
    i < PIEZO_TEST_COUNT;
    i++
  ) {

    Serial.println();

    Serial.print(
      "Piezo Test "
    );

    Serial.print(
      i + 1
    );

    Serial.println("/3");

    // Strike
    data.piezo[i] =
      readPiezoStrike();

    stopServo();

    if (
      !systemRunning
    ) {

      return false;
    }

    Serial.print(
      "Peak = "
    );

    Serial.println(
      data.piezo[i]
    );

    // Return
    if (
      !smartDelay(150)
    ) {

      return false;
    }

    leftServo();

    if (
      !smartDelay(
        SERVO_TURN_TIME
      )
    ) {

      return false;
    }

    stopServo();

    if (
      i <
      PIEZO_TEST_COUNT - 1
    ) {

      if (
        !smartDelay(
          PIEZO_BETWEEN_HITS
        )
      ) {

        return false;
      }
    }
  }

  return true;
}

// =====================================================
// PIEZO TYPE
// =====================================================
ObjectType piezoToType(
  int peak
) {

  if (
    peak >=
    GLASS_MIN
  ) {

    return TYPE_GLASS;
  }

  if (
    peak <
    3000
  ) {

    return TYPE_PLASTIC;
  }

  return TYPE_UNKNOWN;
}

// =====================================================
// CLASSIFICATION
// =====================================================
ObjectType classifyObject(
  SensorData &data
) {

  // Metal priority
  if (
    data.metalDetected
  ) {

    return TYPE_METAL;
  }

  int plasticScore = 0;
  int glassScore = 0;
  int unknownPiezo = 0;

  Serial.println();
  Serial.println("================================");
  Serial.println("CLASSIFICATION EVIDENCE");
  Serial.println("================================");

  // ===================================================
  // PIEZO x3
  // ===================================================
  for (
    int i = 0;
    i < PIEZO_TEST_COUNT;
    i++
  ) {

    ObjectType type =
      piezoToType(
        data.piezo[i]
      );

    Serial.print(
      "Piezo "
    );

    Serial.print(
      i + 1
    );

    Serial.print(
      " = "
    );

    Serial.print(
      data.piezo[i]
    );

    Serial.print(
      " -> "
    );

    if (
      type ==
      TYPE_GLASS
    ) {

      glassScore++;

      Serial.println(
        "GLASS"
      );

    } else if (
      type ==
      TYPE_PLASTIC
    ) {

      plasticScore++;

      Serial.println(
        "PLASTIC"
      );

    } else {

      unknownPiezo++;

      Serial.println(
        "UNKNOWN"
      );
    }
  }

  // ===================================================
  // WEIGHT SUPPORT
  // ===================================================
  if (
    data.weightValid
  ) {

    Serial.print(
      "Object Weight = "
    );

    Serial.print(
      data.weight,
      1
    );

    Serial.println(" g");

    // Light
    if (
      data.weight <=
      LIGHT_WEIGHT_MAX
    ) {

      plasticScore++;

      Serial.println(
        "Weight Vote -> PLASTIC"
      );
    }

    // Heavy
    else if (
      data.weight >=
      HEAVY_WEIGHT_MIN
    ) {

      glassScore++;

      Serial.println(
        "Weight Vote -> GLASS"
      );
    }

    // Middle
    else {

      Serial.println(
        "Weight Vote -> NONE"
      );
    }

  } else {

    Serial.println(
      "Weight -> INVALID / NOT USED"
    );
  }

  Serial.println(
    "--------------------------------"
  );

  Serial.print(
    "Plastic Score = "
  );

  Serial.println(
    plasticScore
  );

  Serial.print(
    "Glass Score   = "
  );

  Serial.println(
    glassScore
  );

  Serial.print(
    "Unknown Piezo = "
  );

  Serial.println(
    unknownPiezo
  );

  // ===================================================
  // WEIGHT INVALID
  // ===================================================
  if (
    !data.weightValid
  ) {

    if (
      plasticScore == 3 &&
      glassScore == 0
    ) {

      return TYPE_PLASTIC;
    }

    if (
      glassScore == 3 &&
      plasticScore == 0
    ) {

      return TYPE_GLASS;
    }

    return TYPE_UNKNOWN;
  }

  // ===================================================
  // WEIGHT VALID
  // ===================================================
  if (
    plasticScore >= 2 &&
    (
      plasticScore -
      glassScore
    ) >= 2
  ) {

    return TYPE_PLASTIC;
  }

  if (
    glassScore >= 2 &&
    (
      glassScore -
      plasticScore
    ) >= 2
  ) {

    return TYPE_GLASS;
  }

  return TYPE_UNKNOWN;
}

// =====================================================
// PRINT RESULT
// =====================================================
void printResult(
  ObjectType type
) {

  Serial.println();
  Serial.println("================================");
  Serial.println("FINAL RESULT");
  Serial.println("================================");

  switch (
    type
  ) {

    case TYPE_GLASS:

      Serial.println(
        "RESULT : GLASS"
      );

      Serial.println(
        "TYPE   : แก้ว"
      );

      Serial.println(
        "SORT   : CH3"
      );

      break;

    case TYPE_PLASTIC:

      Serial.println(
        "RESULT : PLASTIC"
      );

      Serial.println(
        "TYPE   : พลาสติก"
      );

      Serial.println(
        "SORT   : CH1"
      );

      break;

    case TYPE_METAL:

      Serial.println(
        "RESULT : METAL"
      );

      Serial.println(
        "TYPE   : โลหะ"
      );

      Serial.println(
        "SORT   : CH2"
      );

      break;

    default:

      Serial.println(
        "RESULT : UNKNOWN"
      );

      Serial.println(
        "TYPE   : ไม่ทราบ"
      );

      Serial.println(
        "SORT   : NONE"
      );

      break;
  }

  Serial.println(
    "================================"
  );
}

// =====================================================
// STEPPER
// =====================================================
bool rotateStepper(
  float angle
) {

  long steps =
    round(
      (
        fabs(angle) /
        360.0
      ) *
      STEPS_PER_REV
    );

  if (
    angle > 0
  ) {

    digitalWrite(
      DIR_PIN,
      HIGH
    );

  } else {

    digitalWrite(
      DIR_PIN,
      LOW
    );
  }

  delay(10);

  for (
    long i = 0;
    i < steps;
    i++
  ) {

    digitalWrite(
      STEP_PIN,
      HIGH
    );

    delayMicroseconds(
      STEP_DELAY_US
    );

    digitalWrite(
      STEP_PIN,
      LOW
    );

    delayMicroseconds(
      STEP_DELAY_US
    );

    serviceAllLoadCells();

    if (
      i % 20 == 0
    ) {

      checkSerial();

      if (
        !systemRunning
      ) {

        digitalWrite(
          STEP_PIN,
          LOW
        );

        return false;
      }
    }
  }

  return true;
}

// =====================================================
// OPEN MAIN DOOR
// =====================================================
bool openDoor() {

  Serial.println();
  Serial.println("------------------------------");
  Serial.println("STEPPER -> OPEN DOOR");
  Serial.println("------------------------------");

  if (
    !rotateStepper(
      DOOR_OPEN_ANGLE
    )
  ) {

    return false;
  }

  Serial.println(
    "DOOR OPEN"
  );

  return true;
}

// =====================================================
// CLOSE MAIN DOOR
// =====================================================
bool closeDoor() {

  Serial.println();
  Serial.println("------------------------------");
  Serial.println("STEPPER -> CLOSE DOOR");
  Serial.println("------------------------------");

  if (
    !rotateStepper(
      DOOR_CLOSE_ANGLE
    )
  ) {

    return false;
  }

  Serial.println(
    "DOOR CLOSED"
  );

  return true;
}

// =====================================================
// WAIT OBJECT LEAVE
// =====================================================
bool waitObjectLeaveByWeight() {

  Serial.println();
  Serial.println("------------------------------");
  Serial.println("รอวัตถุออก...");
  Serial.println("Timeout = 10 sec");
  Serial.println("------------------------------");

  int emptyCount = 0;

  unsigned long startTime =
    millis();

  while (
    systemRunning
  ) {

    checkSerial();

    serviceBinLoadCells();

    if (
      !systemRunning
    ) {

      return false;
    }

    // =================================================
    // TIMEOUT
    // =================================================
    if (
      millis() -
      startTime >=
      OBJECT_LEAVE_TIMEOUT
    ) {

      Serial.println();
      Serial.println("================================");
      Serial.println("OBJECT LEAVE TIMEOUT");
      Serial.println("================================");

      return false;
    }

    // =================================================
    // INSPECTION LOAD CELL
    // =================================================
    if (
      LoadCell.update()
    ) {

      float raw =
        LoadCell.getData();

      float netWeight =
        raw -
        emptyWeight;

      float distance =
        fabs(
          netWeight
        );

      Serial.print(
        "Raw = "
      );

      Serial.print(
        raw,
        1
      );

      Serial.print(
        " | Net = "
      );

      Serial.print(
        netWeight,
        1
      );

      Serial.println(
        " g"
      );

      if (
        distance <=
        EMPTY_RETURN_TOLERANCE
      ) {

        emptyCount++;

      } else {

        emptyCount = 0;
      }

      if (
        emptyCount >=
        EMPTY_CONFIRM_COUNT
      ) {

        Serial.println();
        Serial.println(
          "OBJECT REMOVED"
        );

        return true;
      }
    }

    delay(20);
  }

  return false;
}

// =====================================================
// HC-SR04
// =====================================================
float readUltrasonicCM(
  int trigPin,
  int echoPin
) {

  digitalWrite(
    trigPin,
    LOW
  );

  delayMicroseconds(3);

  digitalWrite(
    trigPin,
    HIGH
  );

  delayMicroseconds(10);

  digitalWrite(
    trigPin,
    LOW
  );

  unsigned long duration =
    pulseIn(
      echoPin,
      HIGH,
      ULTRASONIC_TIMEOUT_US
    );

  if (
    duration == 0
  ) {

    return -1.0f;
  }

  float cm =
    (
      duration *
      0.0343f
    ) /
    2.0f;

  return cm;
}

// =====================================================
// DISTANCE -> PERCENT
// =====================================================
float distanceToPercent(
  float distance,
  float emptyDistance,
  float fullDistance
) {

  if (
    distance < 0
  ) {

    return -1;
  }

  // 0%
  if (
    distance >=
    emptyDistance
  ) {

    return 0;
  }

  // 100%
  if (
    distance <=
    fullDistance
  ) {

    return 100;
  }

  float percent =
    (
      emptyDistance -
      distance
    )
    /
    (
      emptyDistance -
      fullDistance
    )
    *
    100.0f;

  if (
    percent < 0
  ) {

    percent = 0;
  }

  if (
    percent > 100
  ) {

    percent = 100;
  }

  return percent;
}

// =====================================================
// UPDATE ONE ULTRASONIC
// =====================================================
void updateOneUltrasonic() {

  if (
    millis() -
    lastUltrasonicTime <
    ULTRASONIC_INTERVAL
  ) {

    return;
  }

  lastUltrasonicTime =
    millis();

  // ===================================================
  // U1
  // ===================================================
  if (
    ultrasonicIndex == 0
  ) {

    float d =
      readUltrasonicCM(
        U1_TRIG,
        U1_ECHO
      );

    bin1.distance =
      d;

    bin1.distanceValid =
      d >= 0;

    if (
      bin1.distanceValid
    ) {

      bin1.percent =
        distanceToPercent(
          d,
          U1_EMPTY_DISTANCE,
          U1_FULL_DISTANCE
        );
    }

    ultrasonicIndex =
      1;
  }

  // ===================================================
  // U2
  // ===================================================
  else if (
    ultrasonicIndex == 1
  ) {

    float d =
      readUltrasonicCM(
        U2_TRIG,
        U2_ECHO
      );

    bin2.distance =
      d;

    bin2.distanceValid =
      d >= 0;

    if (
      bin2.distanceValid
    ) {

      bin2.percent =
        distanceToPercent(
          d,
          U2_EMPTY_DISTANCE,
          U2_FULL_DISTANCE
        );
    }

    ultrasonicIndex =
      2;
  }

  // ===================================================
  // U3
  // ===================================================
  else {

    float d =
      readUltrasonicCM(
        U3_TRIG,
        U3_ECHO
      );

    bin3.distance =
      d;

    bin3.distanceValid =
      d >= 0;

    if (
      bin3.distanceValid
    ) {

      bin3.percent =
        distanceToPercent(
          d,
          U3_EMPTY_DISTANCE,
          U3_FULL_DISTANCE
        );
    }

    ultrasonicIndex =
      0;

    binStatusReady =
      true;
  }
}

// =====================================================
// PRINT BIN STATUS
// =====================================================
void printBinStatus() {

  Serial.println();
  Serial.println("================================");
  Serial.println("BIN STATUS");
  Serial.println("================================");

  // BIN 1
  Serial.print(
    "BIN1 | "
  );

  if (
    bin1.distanceValid
  ) {

    Serial.print(
      "Distance="
    );

    Serial.print(
      bin1.distance,
      2
    );

    Serial.print(
      "cm | Level="
    );

    Serial.print(
      bin1.percent,
      1
    );

    Serial.print("%");

  } else {

    Serial.print(
      "Distance=ERROR | Level=ERROR"
    );
  }

  Serial.print(
    " | Weight="
  );

  Serial.print(
    bin1.weight,
    1
  );

  Serial.println("g");

  // BIN 2
  Serial.print(
    "BIN2 | "
  );

  if (
    bin2.distanceValid
  ) {

    Serial.print(
      "Distance="
    );

    Serial.print(
      bin2.distance,
      2
    );

    Serial.print(
      "cm | Level="
    );

    Serial.print(
      bin2.percent,
      1
    );

    Serial.print("%");

  } else {

    Serial.print(
      "Distance=ERROR | Level=ERROR"
    );
  }

  Serial.print(
    " | Weight="
  );

  Serial.print(
    bin2.weight,
    1
  );

  Serial.println("g");

  // BIN 3
  Serial.print(
    "BIN3 | "
  );

  if (
    bin3.distanceValid
  ) {

    Serial.print(
      "Distance="
    );

    Serial.print(
      bin3.distance,
      2
    );

    Serial.print(
      "cm | Level="
    );

    Serial.print(
      bin3.percent,
      1
    );

    Serial.print("%");

  } else {

    Serial.print(
      "Distance=ERROR | Level=ERROR"
    );
  }

  Serial.print(
    " | Weight="
  );

  Serial.print(
    bin3.weight,
    1
  );

  Serial.println("g");

  Serial.println(
    "================================"
  );
}

// =====================================================
// BIN MONITOR
// =====================================================
void monitorBinsWhileIdle() {

  serviceBinLoadCells();

  updateOneUltrasonic();

  if (
    binStatusReady
  ) {

    binStatusReady =
      false;

    printBinStatus();
  }
}

// =====================================================
// SETUP
// =====================================================
void setup() {

  Serial.begin(
    115200
  );

  // ===================================================
  // PHOTO
  // ===================================================
  pinMode(
    PHOTO_PIN,
    INPUT
  );

  // ===================================================
  // PIEZO
  // ===================================================
  pinMode(
    PIEZO_PIN,
    INPUT
  );

  analogReadResolution(
    12
  );

  // ===================================================
  // METAL
  // ===================================================
  pinMode(
    METAL_PIN,
    INPUT_PULLUP
  );

  // ===================================================
  // STEPPER
  // ===================================================
  pinMode(
    STEP_PIN,
    OUTPUT
  );

  pinMode(
    DIR_PIN,
    OUTPUT
  );

  pinMode(
    EN_PIN,
    OUTPUT
  );

  digitalWrite(
    STEP_PIN,
    LOW
  );

  digitalWrite(
    EN_PIN,
    LOW
  );

  // ===================================================
  // HC-SR04
  // ===================================================
  pinMode(
    U1_TRIG,
    OUTPUT
  );

  pinMode(
    U1_ECHO,
    INPUT
  );

  pinMode(
    U2_TRIG,
    OUTPUT
  );

  pinMode(
    U2_ECHO,
    INPUT
  );

  pinMode(
    U3_TRIG,
    OUTPUT
  );

  pinMode(
    U3_ECHO,
    INPUT
  );

  digitalWrite(
    U1_TRIG,
    LOW
  );

  digitalWrite(
    U2_TRIG,
    LOW
  );

  digitalWrite(
    U3_TRIG,
    LOW
  );

  // ===================================================
  // PCA9685
  // ===================================================
  Wire.begin(
    21,
    22
  );

  pwm.begin();

  pwm.setPWMFreq(
    SERVO_PWM_FREQUENCY
  );

  delay(10);

  // CH0
  stopServo();

  // CH1 CH2 CH3
  stopAllSortServos();

  // ===================================================
  // INSPECTION HX711
  // ===================================================
  Serial.println();
  Serial.println(
    "Starting Inspection Load Cell..."
  );

  LoadCell.begin();

  LoadCell.start(
    3000,
    true
  );

  if (
    LoadCell.getTareTimeoutFlag()
  ) {

    Serial.println(
      "Inspection HX711 Timeout!"
    );
  }

  LoadCell.setCalFactor(
    calibrationValue
  );

  // ===================================================
  // BIN HX711 #1
  // ===================================================
  Serial.println(
    "Starting BIN HX711 #1..."
  );

  BinLoad1.begin();

  BinLoad1.start(
    2000,
    true
  );

  BinLoad1.setCalFactor(
    binCalibration1
  );

  // ===================================================
  // BIN HX711 #2
  // ===================================================
  Serial.println(
    "Starting BIN HX711 #2..."
  );

  BinLoad2.begin();

  BinLoad2.start(
    2000,
    true
  );

  BinLoad2.setCalFactor(
    binCalibration2
  );

  // ===================================================
  // BIN HX711 #3
  // ===================================================
  Serial.println(
    "Starting BIN HX711 #3..."
  );

  BinLoad3.begin();

  BinLoad3.start(
    2000,
    true
  );

  BinLoad3.setCalFactor(
    binCalibration3
  );

  // ===================================================
  // INITIAL INSPECTION ZERO
  // ===================================================
  delay(500);

  float total = 0;

  int count = 0;

  unsigned long start =
    millis();

  while (
    count < 15 &&
    millis() -
    start <
    5000
  ) {

    serviceBinLoadCells();

    if (
      LoadCell.update()
    ) {

      total +=
        LoadCell.getData();

      count++;
    }
  }

  if (
    count > 0
  ) {

    emptyWeight =
      total /
      count;
  }

  // ===================================================
  // INITIAL BIN DATA
  // ===================================================
  bin1.distance = -1;
  bin1.percent = 0;
  bin1.weight = 0;
  bin1.distanceValid = false;

  bin2.distance = -1;
  bin2.percent = 0;
  bin2.weight = 0;
  bin2.distanceValid = false;

  bin3.distance = -1;
  bin3.percent = 0;
  bin3.weight = 0;
  bin3.distanceValid = false;

  // ===================================================
  // INFO
  // ===================================================
  Serial.println();
  Serial.println("================================");
  Serial.println("SMART SORTING SYSTEM READY");
  Serial.println("================================");

  Serial.println();
  Serial.println("SORT SERVO:");

  Serial.println(
    "CH1 = PLASTIC"
  );

  Serial.println(
    "CH2 = METAL"
  );

  Serial.println(
    "CH3 = GLASS"
  );

  Serial.println(
    "OPEN  = RIGHT (410) 1 sec"
  );

  Serial.println(
    "CLOSE = LEFT (205) 1 sec"
  );

  Serial.println(
    "STOP  = NEUTRAL (320)"
  );

  Serial.println();

  Serial.println(
    "Plastic Piezo < 3000"
  );

  Serial.println(
    "Glass Piezo >= 3000"
  );

  Serial.println();

  Serial.println(
    "s = START / STOP"
  );

  Serial.println(
    "t = TARE BIN LOAD CELLS"
  );

  Serial.println(
    "w = RESET WI-FI / DEVICE KEY"
  );

  Serial.println("================================");

  // เริ่ม WiFiManager หลังจากเซนเซอร์และมอเตอร์พร้อมแล้ว
  setupCloud();

  Serial.println("SETUP COMPLETE -> ENTER MAIN LOOP");
}

// =====================================================
// LOOP
// =====================================================
void loop() {

  static bool loopStarted = false;
  if (!loopStarted) {
    loopStarted = true;
    Serial.println("MAIN LOOP STARTED");
  }

  // รับเฉพาะคำสั่งฮาร์ดแวร์จาก Queue; งาน HTTPS อยู่บน Core 0
  // จึงไม่บล็อกการอ่าน Photo Sensor ใน Arduino loop
  serviceCloud();

  // ===================================================
  // UPDATE HX711
  // ===================================================
  serviceAllLoadCells();

  // ===================================================
  // SERIAL
  // ===================================================
  checkSerial();

  // ===================================================
  // STOP
  //
  // Sorting หยุด
  // Bin Monitor ยังอ่านได้
  // ===================================================
  if (
    !systemRunning
  ) {

    stopServo();

    stopAllSortServos();

    monitorBinsWhileIdle();

    delay(2);

    return;
  }

  // ===================================================
  // START
  //
  // ปิดประตูหลักทุกครั้ง
  // ===================================================
  if (
    closeDoorOnStartRequested
  ) {

    closeDoorOnStartRequested =
      false;

    Serial.println();
    Serial.println("================================");
    Serial.println("START -> CLOSE MAIN DOOR");
    Serial.println("================================");

    if (
      !closeDoor()
    ) {

      return;
    }

    if (
      !systemRunning
    ) {

      return;
    }

    if (
      !smartDelay(700)
    ) {

      return;
    }

    // =================================================
    // AUTO ZERO จุดตรวจ
    // =================================================
    if (
      !autoZeroLoadCell()
    ) {

      return;
    }

    Serial.println();
    Serial.println("================================");
    Serial.println("SYSTEM READY");
    Serial.println("รอ Photo Sensor...");
    Serial.println("================================");

    cloudMachineReady = true;

    return;
  }

  // ===================================================
  // WAIT PHOTO
  //
  // ระหว่างรอ อ่าน Bin Sensor ด้วย
  // ===================================================
  monitorBinsWhileIdle();

  if (
    !detectPhotoTrigger()
  ) {

    delay(1);

    return;
  }

  if (
    !systemRunning
  ) {

    return;
  }

  // ===================================================
  // PHOTO เจอวัตถุชิ้นใหม่
  //
  // ก่อนอื่นปิด Sort Gate
  // ที่เปิดจากรอบก่อน
  // ===================================================
  Serial.println();
  Serial.println("================================");
  Serial.println("NEW OBJECT DETECTED");
  Serial.println("CLOSE PREVIOUS SORT GATE");
  Serial.println("================================");

  if (
    !closePreviousSortGate()
  ) {

    return;
  }

  if (
    !systemRunning
  ) {

    return;
  }

  // ===================================================
  // OBJECT ENTERED
  // ===================================================
  Serial.println();
  Serial.println("================================");
  Serial.println("OBJECT DETECTED BY PHOTO");
  Serial.println("ถือว่าวัตถุเข้าระบบแล้ว");
  Serial.println("================================");

  // ===================================================
  // WAIT 2 SEC + WATCH METAL
  // ===================================================
  if (
    !waitAfterPhotoAndWatchMetal()
  ) {

    return;
  }

  if (
    !systemRunning
  ) {

    return;
  }

  // ===================================================
  // PREPARE DATA
  // ===================================================
  SensorData data;

  data.weight =
    0;

  data.weightValid =
    false;

  data.metalDetected =
    false;

  data.result =
    TYPE_UNKNOWN;

  for (
    int i = 0;
    i < PIEZO_TEST_COUNT;
    i++
  ) {

    data.piezo[i] =
      0;
  }

  // ===================================================
  // METAL FIRST
  // ===================================================
  data.metalDetected =
    detectMetalStable();

  if (
    !systemRunning
  ) {

    return;
  }

  // ===================================================
  // METAL
  // ===================================================
  if (
    data.metalDetected
  ) {

    data.result =
      TYPE_METAL;

    printResult(
      data.result
    );
  }

  // ===================================================
  // NOT METAL
  // ===================================================
  else {

    // =================================================
    // PIEZO x3
    // =================================================
    if (
      !runPiezoTests(
        data
      )
    ) {

      return;
    }

    if (
      !smartDelay(500)
    ) {

      return;
    }

    // =================================================
    // OBJECT WEIGHT
    // =================================================
    Serial.println();
    Serial.println(
      "Trying to read object weight..."
    );

    float stableRaw = 0;

    if (
      readStableWeight(
        stableRaw
      )
    ) {

      float objectWeight =
        stableRaw -
        emptyWeight;

      Serial.print(
        "Object Net Weight = "
      );

      Serial.print(
        objectWeight,
        1
      );

      Serial.println(" g");

      if (
        objectWeight >= 0 &&
        objectWeight <=
        MAX_VALID_OBJECT_WEIGHT
      ) {

        data.weight =
          objectWeight;

        data.weightValid =
          true;

      } else {

        data.weight =
          0;

        data.weightValid =
          false;

        Serial.println(
          "Weight ignored"
        );
      }

    } else {

      data.weight =
        0;

      data.weightValid =
        false;

      Serial.println(
        "Weight unstable / ignored"
      );
    }

    // =================================================
    // CLASSIFY
    // =================================================
    data.result =
      classifyObject(
        data
      );

    printResult(
      data.result
    );
  }

  if (
    !systemRunning
  ) {

    return;
  }

  // ===================================================
  // OPEN SORT GATE
  //
  // Plastic -> CH1
  // Metal   -> CH2
  // Glass   -> CH3
  // Unknown -> NONE
  // ===================================================
  if (
    !openGateForType(
      data.result
    )
  ) {

    return;
  }

  if (
    !systemRunning
  ) {

    return;
  }

  // ===================================================
  // OPEN MAIN DOOR
  // ===================================================
  if (
    !openDoor()
  ) {

    return;
  }

  Serial.println();
  Serial.println(
    "รอวัตถุตกออก..."
  );

  if (
    !smartDelay(
      DOOR_WAIT_TIME
    )
  ) {

    return;
  }

  // ===================================================
  // WAIT OBJECT LEAVE
  // ===================================================
  bool objectRemoved =
    waitObjectLeaveByWeight();

  if (
    !systemRunning
  ) {

    return;
  }

  // ===================================================
  // CLOSE MAIN DOOR
  //
  // Sort Gate CH1-3 ยังเปิดอยู่
  // จะปิดเมื่อ Photo เจอชิ้นถัดไป
  // ===================================================
  if (
    !closeDoor()
  ) {

    return;
  }

  if (
    !systemRunning
  ) {

    return;
  }

  // ===================================================
  // LEAVE TIMEOUT
  //
  // ระบบยังทำต่อ
  // ===================================================
  if (
    !objectRemoved
  ) {

    Serial.println();
    Serial.println("================================");
    Serial.println("OBJECT LEAVE TIMEOUT");
    Serial.println("MAIN DOOR = CLOSED");
    Serial.println("AUTO ZERO = SKIPPED");
    Serial.println("SYSTEM = CONTINUE");
    Serial.println("================================");

    metalLatched =
      false;

    return;
  }

  // ===================================================
  // AUTO ZERO INSPECTION LOAD CELL
  // ===================================================
  if (
    !autoZeroLoadCell()
  ) {

    return;
  }

  // ===================================================
  // NEXT ROUND
  // ===================================================
  metalLatched =
    false;

  Serial.println();
  Serial.println("================================");
  Serial.println("READY FOR NEXT OBJECT");
  Serial.println("================================");

  if (
    lastOpenedServoChannel !=
    -1
  ) {

    Serial.print(
      "Sort Gate currently open = CH"
    );

    Serial.println(
      lastOpenedServoChannel
    );

    Serial.println(
      "จะปิดเมื่อ Photo เจอวัตถุชิ้นถัดไป"
    );
  }

  Serial.println(
    "รอ Photo Sensor..."
  );
}
