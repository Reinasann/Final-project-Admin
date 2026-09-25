/*
 * Smart Recycle cloud integration
 *
 * Add this file as a second Arduino IDE tab next to the existing sorting
 * controller sketch. The main sketch must call setupCloud() once in setup(),
 * and serviceCloud() continuously from loop(). Network I/O runs on Core 0;
 * serviceCloud() only executes queued hardware commands on the main loop.
 *
 * Required libraries:
 *   - WiFiManager by tzapu (2.0.17 or newer)
 *   - ArduinoJson by Benoit Blanchon (7.x)
 */

const char *API_BASE_URL = "https://smart-recycle-admin.onrender.com";
const unsigned long TELEMETRY_INTERVAL_MS = 60000UL;
const unsigned long COMMAND_POLL_INTERVAL_MS = 2000UL;
const unsigned long WIFI_RETRY_INTERVAL_MS = 10000UL;
const unsigned long STATE_RECONCILE_INTERVAL_MS = 30000UL;

Preferences cloudPreferences;
WiFiClientSecure cloudSecureClient;

char cloudDeviceId[31] = "";
char cloudDeviceKey[129] = "";

struct CloudCommandMessage {
  long commandId;
  char commandType[16];
  char wasteType[12];
};

struct CloudAckMessage {
  long commandId;
  bool success;
  char message[80];
};

QueueHandle_t cloudCommandQueue = nullptr;
QueueHandle_t cloudAckQueue = nullptr;
TaskHandle_t cloudNetworkTaskHandle = nullptr;
volatile bool cloudCommandInProgress = false;

unsigned long lastTelemetryAt = 0;
unsigned long lastCommandPollAt = 0;
unsigned long lastWifiRetryAt = 0;
unsigned long lastStateReconcileAt = 0;
int lastReportedDesiredState = -1;

void cloudNetworkTask(void *parameter);

String jsonResponseBody(HTTPClient &http) {
  String body = http.getString();
  http.end();
  return body;
}

bool cloudCredentialsReady() {
  return strlen(cloudDeviceId) > 0 && strlen(cloudDeviceKey) > 0;
}

void saveCloudCredentials(const char *deviceId, const char *deviceKey) {
  strlcpy(cloudDeviceId, deviceId, sizeof(cloudDeviceId));
  strlcpy(cloudDeviceKey, deviceKey, sizeof(cloudDeviceKey));
  cloudPreferences.begin("smart-recycle", false);
  cloudPreferences.putString("device_id", cloudDeviceId);
  cloudPreferences.putString("device_key", cloudDeviceKey);
  cloudPreferences.end();
}

void loadCloudCredentials() {
  cloudPreferences.begin("smart-recycle", true);
  String savedId = cloudPreferences.getString("device_id", "");
  String savedKey = cloudPreferences.getString("device_key", "");
  cloudPreferences.end();
  strlcpy(cloudDeviceId, savedId.c_str(), sizeof(cloudDeviceId));
  strlcpy(cloudDeviceKey, savedKey.c_str(), sizeof(cloudDeviceKey));
}

bool openCloudConfigurationPortal() {
  WiFiManager wifiManager;
  WiFiManagerParameter deviceIdParameter(
    "device_id",
    "Serial Number เช่น ESP32-SR-001",
    cloudDeviceId,
    sizeof(cloudDeviceId)
  );
  WiFiManagerParameter deviceKeyParameter(
    "device_key",
    "Device API Key",
    cloudDeviceKey,
    sizeof(cloudDeviceKey),
    "type=\"password\""
  );

  wifiManager.addParameter(&deviceIdParameter);
  wifiManager.addParameter(&deviceKeyParameter);
  wifiManager.setConfigPortalTimeout(180);

  bool connected;
  if (cloudCredentialsReady()) {
    connected = wifiManager.autoConnect(
      "SmartRecycle-Setup",
      "smartrecycle"
    );
  } else {
    connected = wifiManager.startConfigPortal(
      "SmartRecycle-Setup",
      "smartrecycle"
    );
  }

  if (!connected) {
    Serial.println("WiFiManager: connection/configuration timed out");
    return false;
  }

  saveCloudCredentials(
    deviceIdParameter.getValue(),
    deviceKeyParameter.getValue()
  );
  return cloudCredentialsReady();
}

void resetCloudConfiguration() {
  if (cloudNetworkTaskHandle != nullptr) {
    vTaskSuspend(cloudNetworkTaskHandle);
  }
  WiFiManager wifiManager;
  wifiManager.resetSettings();
  cloudPreferences.begin("smart-recycle", false);
  cloudPreferences.clear();
  cloudPreferences.end();
  cloudDeviceId[0] = '\0';
  cloudDeviceKey[0] = '\0';
  Serial.println("Wi-Fi and device credentials cleared. Restart ESP32 to configure again.");
}

void setupCloud() {
  loadCloudCredentials();
  WiFi.mode(WIFI_STA);

  Serial.println();
  Serial.println("Connecting with WiFiManager...");
  if (!openCloudConfigurationPortal()) {
    Serial.println("Cloud integration is not configured.");
    return;
  }

  // For production, replace setInsecure() with the Render root CA certificate.
  cloudSecureClient.setInsecure();
  Serial.print("Wi-Fi connected, IP: ");
  Serial.println(WiFi.localIP());
  Serial.print("Device ID: ");
  Serial.println(cloudDeviceId);

  cloudCommandQueue = xQueueCreate(1, sizeof(CloudCommandMessage));
  cloudAckQueue = xQueueCreate(2, sizeof(CloudAckMessage));
  if (cloudCommandQueue == nullptr || cloudAckQueue == nullptr) {
    Serial.println("Cloud queue creation failed");
    return;
  }

  // อนุญาตให้คืนสถานะ START/STOP จาก Django ได้ทันทีหลังรีสตาร์ต
  lastStateReconcileAt = millis() - STATE_RECONCILE_INTERVAL_MS;

  BaseType_t taskCreated = xTaskCreatePinnedToCore(
    cloudNetworkTask,
    "smart-recycle-network",
    8192,
    nullptr,
    0,
    &cloudNetworkTaskHandle,
    0
  );
  if (taskCreated != pdPASS) {
    Serial.println("Cloud network task creation failed");
  } else {
    Serial.println("Cloud network task created on Core 0 (low priority)");
  }
}

void stopMachineFromCloud() {
  systemRunning = false;
  cloudMachineReady = false;
  closeDoorOnStartRequested = false;
  photoTriggered = false;
  metalLatched = false;
  stopServo();
  stopAllSortServos();
  digitalWrite(STEP_PIN, LOW);
  Serial.println("Cloud command: SYSTEM STOP");
}

bool startMachineFromCloud() {
  if (systemRunning) {
    return true;
  }

  systemRunning = true;
  cloudMachineReady = false;
  closeDoorOnStartRequested = false;
  photoTriggered = false;
  metalLatched = false;

  // Option 1 selected: close/reset all three sorting gates in sequence.
  const int channels[] = {
    PLASTIC_SERVO_CH,
    METAL_SERVO_CH,
    GLASS_SERVO_CH
  };
  for (int index = 0; index < 3; index++) {
    Serial.print("START -> CLOSE SORT SERVO CH");
    Serial.println(channels[index]);

    if (!moveSortServo(channels[index], SERVO_LEFT, SORT_SERVO_TIME)) {
      stopMachineFromCloud();
      return false;
    }

    Serial.print("SORT SERVO CH");
    Serial.print(channels[index]);
    Serial.println(" = CLOSED");
  }
  lastOpenedServoChannel = -1;

  // The existing loop will close the main stepper door and auto-zero the
  // inspection load cell before it starts accepting objects.
  closeDoorOnStartRequested = true;
  Serial.println("Cloud command: SYSTEM START; all sorting gates closed");
  return true;
}

bool tareSelectedBin(HX711_ADC &loadCell, BinData &binData) {
  if (systemRunning) {
    return false;
  }

  loadCell.tareNoDelay();
  unsigned long startedAt = millis();
  while (millis() - startedAt < 10000UL) {
    serviceAllLoadCells();
    if (loadCell.getTareStatus()) {
      binData.weight = 0;
      return true;
    }
    delay(1);
  }
  return false;
}

bool resetBinFromCloud(const String &wasteType) {
  if (wasteType == "plastic") {
    return tareSelectedBin(BinLoad1, bin1);
  }
  if (wasteType == "can") {
    return tareSelectedBin(BinLoad2, bin2);
  }
  if (wasteType == "glass") {
    return tareSelectedBin(BinLoad3, bin3);
  }
  return false;
}

bool applyCloudCommand(const char *commandType, const char *wasteType) {
  if (strcmp(commandType, "START") == 0) {
    return startMachineFromCloud();
  }
  if (strcmp(commandType, "STOP") == 0) {
    stopMachineFromCloud();
    return true;
  }
  if (strcmp(commandType, "RESET_BIN") == 0) {
    return resetBinFromCloud(String(wasteType));
  }
  return false;
}

void acknowledgeCloudCommand(
  long commandId,
  bool success,
  const String &message
) {
  HTTPClient http;
  String url = String(API_BASE_URL)
    + "/api/v1/iot/commands/"
    + String(commandId)
    + "/ack/";
  if (!http.begin(cloudSecureClient, url)) {
    return;
  }

  http.setTimeout(3000);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", cloudDeviceKey);
  JsonDocument body;
  body["device_id"] = cloudDeviceId;
  body["success"] = success;
  body["message"] = message;
  String encoded;
  serializeJson(body, encoded);
  int statusCode = http.POST(encoded);
  http.end();
  Serial.printf("Command ACK %ld -> HTTP %d\n", commandId, statusCode);
}

bool queueCloudCommand(
  long commandId,
  const char *commandType,
  const char *wasteType
) {
  if (cloudCommandQueue == nullptr || cloudCommandInProgress) {
    return false;
  }

  CloudCommandMessage message = {};
  message.commandId = commandId;
  strlcpy(message.commandType, commandType, sizeof(message.commandType));
  strlcpy(message.wasteType, wasteType, sizeof(message.wasteType));

  cloudCommandInProgress = true;
  if (xQueueSend(cloudCommandQueue, &message, 0) != pdTRUE) {
    cloudCommandInProgress = false;
    return false;
  }

  // STOP ตัด state ทันทีเพื่อให้ลูปมอเตอร์ที่กำลังทำงานหยุดได้
  // ส่วนการปิดเอาต์พุตทั้งหมดจะทำบน main loop ผ่าน serviceCloud()
  if (strcmp(commandType, "STOP") == 0) {
    systemRunning = false;
    cloudMachineReady = false;
  }
  return true;
}

bool reconcileDesiredMachineState(bool desiredIsOn) {
  if (desiredIsOn == systemRunning) {
    return false;
  }
  if (millis() - lastStateReconcileAt < STATE_RECONCILE_INTERVAL_MS) {
    return false;
  }
  lastStateReconcileAt = millis();
  return queueCloudCommand(
    0,
    desiredIsOn ? "START" : "STOP",
    ""
  );
}

bool pollCloudCommand() {
  HTTPClient http;
  String url = String(API_BASE_URL)
    + "/api/v1/iot/commands/?device_id="
    + cloudDeviceId;
  if (!http.begin(cloudSecureClient, url)) {
    return false;
  }
  http.setTimeout(3000);
  http.addHeader("X-Device-Key", cloudDeviceKey);
  int statusCode = http.GET();
  String response = jsonResponseBody(http);
  if (statusCode != HTTP_CODE_OK) {
    Serial.printf("Command poll failed: HTTP %d\n", statusCode);
    return false;
  }

  JsonDocument document;
  if (deserializeJson(document, response)) {
    Serial.println("Command poll returned invalid JSON");
    return false;
  }

  JsonVariant command = document["command"];
  if (command.isNull()) {
    bool desiredIsOn = document["desired_is_on"] | false;
    int desiredState = desiredIsOn ? 1 : 0;
    if (desiredState != lastReportedDesiredState) {
      lastReportedDesiredState = desiredState;
      Serial.print("Cloud API connected | Desired state = ");
      Serial.println(desiredIsOn ? "ON" : "OFF");
    }
    return reconcileDesiredMachineState(desiredIsOn);
  }

  long commandId = command["id"] | 0;
  const char *commandType = command["type"] | "";
  const char *wasteType = command["payload"]["waste_type"] | "";
  Serial.print("Cloud command received: ");
  Serial.print(commandType);
  Serial.print(" #");
  Serial.println(commandId);
  return queueCloudCommand(
    commandId,
    commandType,
    wasteType
  );
}

void sendCloudTelemetry() {
  HTTPClient http;
  String url = String(API_BASE_URL) + "/api/v1/iot/telemetry/";
  if (!http.begin(cloudSecureClient, url)) {
    return;
  }
  http.setTimeout(3000);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", cloudDeviceKey);

  JsonDocument document;
  document["device_id"] = cloudDeviceId;
  JsonArray bins = document["bins"].to<JsonArray>();

  JsonObject plastic = bins.add<JsonObject>();
  plastic["waste_type"] = "plastic";
  plastic["weight_kg"] = max(0.0f, bin1.weight) / 1000.0f;
  plastic["level_percent"] = constrain(bin1.percent, 0.0f, 100.0f);

  JsonObject can = bins.add<JsonObject>();
  can["waste_type"] = "can";
  can["weight_kg"] = max(0.0f, bin2.weight) / 1000.0f;
  can["level_percent"] = constrain(bin2.percent, 0.0f, 100.0f);

  JsonObject glass = bins.add<JsonObject>();
  glass["waste_type"] = "glass";
  glass["weight_kg"] = max(0.0f, bin3.weight) / 1000.0f;
  glass["level_percent"] = constrain(bin3.percent, 0.0f, 100.0f);

  String encoded;
  serializeJson(document, encoded);
  int statusCode = http.POST(encoded);
  String response = jsonResponseBody(http);
  Serial.printf("Telemetry -> HTTP %d\n", statusCode);
  if (statusCode < 200 || statusCode >= 300) {
    Serial.println(response);
  }
}

void serviceCloud() {
  if (cloudCommandQueue == nullptr || cloudAckQueue == nullptr) {
    return;
  }

  CloudCommandMessage command = {};
  if (xQueueReceive(cloudCommandQueue, &command, 0) != pdTRUE) {
    return;
  }

  bool success = applyCloudCommand(
    command.commandType,
    command.wasteType
  );

  CloudAckMessage acknowledgement = {};
  acknowledgement.commandId = command.commandId;
  acknowledgement.success = success;
  strlcpy(
    acknowledgement.message,
    success ? "Command completed." : "Command could not be completed.",
    sizeof(acknowledgement.message)
  );

  if (xQueueSend(cloudAckQueue, &acknowledgement, 0) != pdTRUE) {
    cloudCommandInProgress = false;
  }
}

void cloudNetworkTask(void *parameter) {
  // ให้ setup() และ Arduino loop เริ่มทำงานก่อนเปิด HTTPS
  vTaskDelay(pdMS_TO_TICKS(3000));
  Serial.println("Cloud network task running");

  for (;;) {
    if (!cloudCredentialsReady()) {
      vTaskDelay(pdMS_TO_TICKS(1000));
      continue;
    }

    if (WiFi.status() != WL_CONNECTED) {
      if (millis() - lastWifiRetryAt >= WIFI_RETRY_INTERVAL_MS) {
        lastWifiRetryAt = millis();
        WiFi.reconnect();
      }
      vTaskDelay(pdMS_TO_TICKS(250));
      continue;
    }

    CloudAckMessage acknowledgement = {};
    if (xQueueReceive(cloudAckQueue, &acknowledgement, 0) == pdTRUE) {
      if (acknowledgement.commandId > 0) {
        acknowledgeCloudCommand(
          acknowledgement.commandId,
          acknowledgement.success,
          acknowledgement.message
        );
      }
      cloudCommandInProgress = false;
    }

    if (
      !cloudCommandInProgress
      && millis() - lastCommandPollAt >= COMMAND_POLL_INTERVAL_MS
    ) {
      lastCommandPollAt = millis();
      pollCloudCommand();
    }

    if (
      cloudMachineReady
      && millis() - lastTelemetryAt >= TELEMETRY_INTERVAL_MS
    ) {
      lastTelemetryAt = millis();
      sendCloudTelemetry();
    }

    vTaskDelay(pdMS_TO_TICKS(20));
  }
}
