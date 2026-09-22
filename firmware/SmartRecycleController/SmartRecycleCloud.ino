/*
 * Smart Recycle cloud integration
 *
 * Add this file as a second Arduino IDE tab next to the existing sorting
 * controller sketch. The main sketch must call setupCloud() once in setup(),
 * and serviceCloud() continuously from loop()/serviceAllLoadCells().
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

bool cloudBusy = false;
unsigned long lastTelemetryAt = 0;
unsigned long lastCommandPollAt = 0;
unsigned long lastWifiRetryAt = 0;
unsigned long lastStateReconcileAt = 0;

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
}

void stopMachineFromCloud() {
  systemRunning = false;
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
    if (!moveSortServo(channels[index], SERVO_LEFT, SORT_SERVO_TIME)) {
      stopMachineFromCloud();
      return false;
    }
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

bool applyCloudCommand(const String &commandType, JsonObject payload) {
  if (commandType == "START") {
    return startMachineFromCloud();
  }
  if (commandType == "STOP") {
    stopMachineFromCloud();
    return true;
  }
  if (commandType == "RESET_BIN") {
    return resetBinFromCloud(payload["waste_type"] | "");
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

void reconcileDesiredMachineState(bool desiredIsOn) {
  if (desiredIsOn == systemRunning) {
    return;
  }
  if (millis() - lastStateReconcileAt < STATE_RECONCILE_INTERVAL_MS) {
    return;
  }
  lastStateReconcileAt = millis();
  if (desiredIsOn) {
    startMachineFromCloud();
  } else {
    stopMachineFromCloud();
  }
}

void pollCloudCommand() {
  HTTPClient http;
  String url = String(API_BASE_URL)
    + "/api/v1/iot/commands/?device_id="
    + cloudDeviceId;
  if (!http.begin(cloudSecureClient, url)) {
    return;
  }
  http.addHeader("X-Device-Key", cloudDeviceKey);
  int statusCode = http.GET();
  String response = jsonResponseBody(http);
  if (statusCode != HTTP_CODE_OK) {
    Serial.printf("Command poll failed: HTTP %d\n", statusCode);
    return;
  }

  JsonDocument document;
  if (deserializeJson(document, response)) {
    Serial.println("Command poll returned invalid JSON");
    return;
  }

  JsonVariant command = document["command"];
  if (command.isNull()) {
    reconcileDesiredMachineState(document["desired_is_on"] | false);
    return;
  }

  long commandId = command["id"] | 0;
  String commandType = command["type"] | "";
  JsonObject payload = command["payload"].as<JsonObject>();
  bool success = applyCloudCommand(commandType, payload);
  acknowledgeCloudCommand(
    commandId,
    success,
    success ? "Command completed." : "Command could not be completed."
  );
}

void sendCloudTelemetry() {
  HTTPClient http;
  String url = String(API_BASE_URL) + "/api/v1/iot/telemetry/";
  if (!http.begin(cloudSecureClient, url)) {
    return;
  }
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
  if (cloudBusy || !cloudCredentialsReady()) {
    return;
  }

  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - lastWifiRetryAt >= WIFI_RETRY_INTERVAL_MS) {
      lastWifiRetryAt = millis();
      WiFi.reconnect();
    }
    return;
  }

  cloudBusy = true;
  if (millis() - lastCommandPollAt >= COMMAND_POLL_INTERVAL_MS) {
    lastCommandPollAt = millis();
    pollCloudCommand();
  }
  if (
    systemRunning
    && millis() - lastTelemetryAt >= TELEMETRY_INTERVAL_MS
  ) {
    lastTelemetryAt = millis();
    sendCloudTelemetry();
  }
  cloudBusy = false;
}
