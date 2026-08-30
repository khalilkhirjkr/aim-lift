#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <WiFiManager.h>     // Library Manager: "WiFiManager" by tzapu (>= 2.0.17)
#include <Preferences.h>
#include <SPI.h>
#include <SD.h>
#include "time.h"
#include <HTTPClient.h>

// ===================================================
// ============== CONFIGURATION ======================
// ===================================================
// WiFi + Device/Lift/Premise are configured ON-SITE via a captive portal
// (no need to re-flash). See "FIELD SETUP" notes at the bottom of this file.

// ==== FIXED (same for every unit) ====
const char* serverUrl      = "https://aim-lift.onrender.com/api/iot/alert/";
const char* statusCheckUrl = "https://aim-lift.onrender.com/api/iot/check_status/";
const char* readingUrl     = "https://aim-lift.onrender.com/api/iot/reading/";
// Must match IOT_DEVICE_KEY on the server (sent as the X-Device-Key header).
const char* deviceKey      = "REPLACE_WITH_IOT_DEVICE_KEY";

// Captive-portal access point shown when the device is unconfigured / offline.
const char* setupApName = "AIM-Lift-Setup";
const char* setupApPass = "aimlift123";   // >= 8 chars; give this to technicians

// ==== RUNTIME CONFIG (set in portal, saved to flash / NVS) ====
String deviceId    = "ESP32-LIFT-01";
String premiseName = "";
String liftId      = "";

// ==== PIN SETUP ====
#define BLACK_BUTTON 26  // Simulates weight sensor (passenger)
#define RED_BUTTON   27  // Simulates emergency button
#define LED_PIN      2
#define BUZZER_PIN   25  // Active-LOW buzzer
#define SD_CS_PIN    5   // Chip Select for SD module

// ===================================================
// =========== END OF CONFIGURATION ==================
// ===================================================

// ==== NTP CONFIG ====
const char* ntpServer = "pool.ntp.org";
const long  gmtOffset_sec = 8 * 3600; // Malaysia time GMT+8
const int   daylightOffset_sec = 0;

// ==== POLLING CONFIG ====
unsigned long lastStatusCheck = 0;
const long statusCheckInterval = 5000; // Check server every 5 seconds

// ==== SYSTEM STATES ====
bool alarmActive = false;
String activeIncidentType = "";
bool lastBlackButtonState = LOW;
bool lastRedButtonState = LOW;

unsigned long resetStartTime = 0;    // Timer for local long-press silence
const long resetDuration = 2000;     // 2000ms = 2 seconds for long press

// SD File
File logFile;

// Persistent config
Preferences prefs;
bool shouldSaveConfig = false;
void saveConfigCallback() { shouldSaveConfig = true; }

// ==== CONFIG PERSISTENCE ====
void loadConfig() {
  prefs.begin("aimlift", true); // read-only
  deviceId    = prefs.getString("deviceId", "ESP32-LIFT-01");
  premiseName = prefs.getString("premise", "");
  liftId      = prefs.getString("liftId", "");
  prefs.end();
}

void saveConfig() {
  prefs.begin("aimlift", false);
  prefs.putString("deviceId", deviceId);
  prefs.putString("premise", premiseName);
  prefs.putString("liftId", liftId);
  prefs.end();
}

// Hold BOTH buttons at power-on for 3s -> wipe WiFi + config, reopen portal.
void maybeFactoryReset() {
  if (digitalRead(BLACK_BUTTON) == HIGH && digitalRead(RED_BUTTON) == HIGH) {
    Serial.println("Both buttons held - keep holding 3s to clear config...");
    unsigned long t0 = millis();
    while (digitalRead(BLACK_BUTTON) == HIGH && digitalRead(RED_BUTTON) == HIGH) {
      if (millis() - t0 > 3000) {
        WiFiManager wm;
        wm.resetSettings();                         // clears saved WiFi
        prefs.begin("aimlift", false);
        prefs.clear();                              // clears device/lift/premise
        prefs.end();
        Serial.println("Config cleared. Restarting...");
        delay(500);
        ESP.restart();
      }
      delay(50);
    }
  }
}

// ==== HELPER: GET TIMESTAMP ====
String getTimestamp() {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) {
    return "TIME_ERROR";
  }
  char buffer[30];
  strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", &timeinfo);
  return String(buffer);
}

// ==== HELPER: LOG DATA TO SD CARD ====
void logEvent(String eventCategory, String eventDetail) {
  String timestamp = getTimestamp();
  String logLine = timestamp + "," + eventCategory + "," + eventDetail; // CSV format

  logFile = SD.open("/lift_log.csv", FILE_APPEND);
  if (logFile) {
    logFile.println(logLine);
    logFile.close();
    Serial.println("LOGGED: " + logLine);
  } else {
    Serial.println("Failed to write to lift_log.csv");
  }
}

// ==== HELPER: SEND ALERT TO DJANGO ====
void sendAlert(String type, String status) {
  if (WiFi.status() == WL_CONNECTED) {
    WiFiClientSecure client;
    client.setInsecure();  // skip TLS cert check (Render uses a Let's Encrypt cert)
    HTTPClient http;
    http.begin(client, serverUrl);
    http.setConnectTimeout(15000);
    http.setTimeout(60000);  // Render free tier can take ~50s to wake from idle
    http.addHeader("Content-Type", "application/json");

    String payload = "{\"device_id\":\"" + deviceId + "\","
                     "\"lift_id\":\"" + liftId + "\","
                     "\"incident_type\":\"" + type + "\","
                     "\"premise\":\"" + premiseName + "\","
                     "\"status\":\"" + status + "\"}";

    int httpResponseCode = http.POST(payload);
    if (httpResponseCode > 0) {
      Serial.printf("Alert sent, Response: %d\n", httpResponseCode);
    } else {
      Serial.printf("Alert failed, Error: %s\n", http.errorToString(httpResponseCode).c_str());
    }
    http.end();
  }
}

// ==== HELPER: SEND A SENSOR READING TO DJANGO ====
// Replace the random values below with real sensor code once sensors are wired.
// abnormal=true sends a fault-like reading (high vibration + acoustic) so the
// predictive-maintenance model + incident flow can be exercised end to end.
void sendReading(bool abnormal) {
  if (WiFi.status() != WL_CONNECTED) { Serial.println("No WiFi."); return; }

  float p1 = random(2970, 3010) / 10.0;      // control panel temp K
  float p2 = random(3080, 3095) / 10.0;      // motor temp K
  float p3 = random(1450, 1550);            // motor speed rpm
  float s1 = random(35, 45);                // torque Nm
  float s2 = random(10, 150);              // operational hours
  float s3 = random(10, 80);
  float vib  = abnormal ? random(200, 500) / 10.0 : random(1, 30) / 10.0;   // mm/s^2
  float vacc = random(1, 15) / 100.0;                                        // m/s^2
  float ac   = abnormal ? random(800, 1000) / 10.0 : random(550, 630) / 10.0; // dB

  String payload = "{";
  payload += "\"lift_id\":\"" + liftId + "\",";
  payload += "\"device_id\":\"" + deviceId + "\",";
  payload += "\"feature_p1\":" + String(p1, 2) + ",";
  payload += "\"feature_p2\":" + String(p2, 2) + ",";
  payload += "\"feature_p3\":" + String(p3, 2) + ",";
  payload += "\"feature_s1\":" + String(s1, 2) + ",";
  payload += "\"feature_s2\":" + String(s2, 2) + ",";
  payload += "\"feature_s3\":" + String(s3, 2) + ",";
  payload += "\"vibration\":" + String(vib, 2) + ",";
  payload += "\"vertical_acceleration_mps2\":" + String(vacc, 3) + ",";
  payload += "\"acoustic_db\":" + String(ac, 2);
  payload += "}";

  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;
  http.begin(client, readingUrl);
  http.setConnectTimeout(15000);
  http.setTimeout(60000);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", deviceKey);

  int code = http.POST(payload);
  if (code > 0) {
    Serial.printf("Reading sent (%s), Response: %d\n", abnormal ? "fault" : "normal", code);
    Serial.println(http.getString());
  } else {
    Serial.printf("Reading failed, Error: %s\n", http.errorToString(code).c_str());
  }
  http.end();
}

// ==== HELPER: CHECK SERVER FOR COMMAND ====
void checkServerForCommand() {
  if (WiFi.status() != WL_CONNECTED) return;

  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;
  String url = String(statusCheckUrl) + "?device_id=" + deviceId + "&incident_type=" + activeIncidentType;

  http.begin(client, url);
  http.setConnectTimeout(15000);
  http.setTimeout(20000);

  int httpResponseCode = http.GET();
  if (httpResponseCode == 200) {
    String payload = http.getString();
    if (payload.indexOf("\"command\":\"silence\"") > -1) {
      Serial.println("SILENCE command received from server!");
      alarmActive = false;
      digitalWrite(LED_PIN, LOW);
      digitalWrite(BUZZER_PIN, HIGH); // Buzzer OFF
      logEvent("INCIDENT_UPDATE", "SILENCED_REMOTELY");
      sendAlert(activeIncidentType, "Attended");
    }
  } else {
    Serial.printf("Status check failed, error: %d\n", httpResponseCode);
  }
  http.end();
}

// ==== BEEP FUNCTION (Active-LOW buzzer) ====
void beepBuzzer() {
  digitalWrite(BUZZER_PIN, LOW);
  delay(150);
  digitalWrite(BUZZER_PIN, HIGH);
  delay(150);
}

// ==========================================
// ============== SETUP =====================
// ==========================================
void setup() {
  Serial.begin(115200);

  pinMode(BLACK_BUTTON, INPUT_PULLDOWN);
  pinMode(RED_BUTTON, INPUT_PULLDOWN);
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);

  digitalWrite(LED_PIN, LOW);
  digitalWrite(BUZZER_PIN, HIGH);

  loadConfig();
  maybeFactoryReset();

  // ---- WiFi + on-site configuration via captive portal ----
  WiFiManager wm;
  WiFiManagerParameter p_device("device", "Device ID", deviceId.c_str(), 40);
  WiFiManagerParameter p_lift("lift", "Lift ID (must match lift_identifier in DB)", liftId.c_str(), 60);
  WiFiManagerParameter p_premise("premise", "Premise name", premiseName.c_str(), 100);
  wm.addParameter(&p_device);
  wm.addParameter(&p_lift);
  wm.addParameter(&p_premise);
  wm.setSaveConfigCallback(saveConfigCallback);
  wm.setConfigPortalTimeout(180); // if nobody configures within 3 min, reboot & retry

  Serial.printf("Starting WiFi. If unconfigured, join AP \"%s\" (pass: %s)\n", setupApName, setupApPass);
  if (!wm.autoConnect(setupApName, setupApPass)) {
    Serial.println("WiFi connect / portal timed out. Restarting...");
    delay(1000);
    ESP.restart();
  }
  Serial.println("WiFi connected!");

  if (shouldSaveConfig) {
    deviceId    = p_device.getValue();
    liftId      = p_lift.getValue();
    premiseName = p_premise.getValue();
    saveConfig();
    Serial.println("On-site config saved.");
  }
  Serial.printf("Device: %s | Lift: %s | Premise: %s\n",
                deviceId.c_str(), liftId.c_str(), premiseName.c_str());

  configTime(gmtOffset_sec, daylightOffset_sec, ntpServer);
  Serial.println("Syncing time with NTP...");
  struct tm ti;
  if (getLocalTime(&ti, 5000)) { // 5-second timeout
    Serial.println("Time synced: " + getTimestamp());
  } else {
    Serial.println("Failed to sync time");
  }

  if (!SD.begin(SD_CS_PIN)) {
    Serial.println("SD Card init failed!");
  } else {
    Serial.println("SD Card ready.");
    logEvent("SYSTEM", "STARTED");
  }

  Serial.println("AIM-Lift Data Logger Ready.");
}

// ==========================================
// ================= LOOP ===================
// ==========================================
// Serial test commands (type in Serial Monitor, no wiring needed):
//   test    -> send a "Mantrap / Detected" alert
//   attend  -> send a "Mantrap / Attended" alert
//   read    -> send one NORMAL sensor reading   (POST /api/iot/reading/)
//   fault   -> send one ABNORMAL sensor reading (triggers predictive-maintenance flow)
//   info    -> print the active Device / Lift / Premise
void handleSerialCommands() {
  if (!Serial.available()) return;
  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  if (cmd == "test") {
    Serial.println(">> Sending test alert (Mantrap / Detected)...");
    sendAlert("Mantrap", "Detected");
  } else if (cmd == "attend") {
    Serial.println(">> Sending test alert (Mantrap / Attended)...");
    sendAlert("Mantrap", "Attended");
  } else if (cmd == "read") {
    Serial.println(">> Sending NORMAL sensor reading...");
    sendReading(false);
  } else if (cmd == "fault") {
    Serial.println(">> Sending ABNORMAL sensor reading...");
    sendReading(true);
  } else if (cmd == "info") {
    Serial.printf("Device: %s | Lift: %s | Premise: %s\n",
                  deviceId.c_str(), liftId.c_str(), premiseName.c_str());
  } else if (cmd.length()) {
    Serial.println(">> Unknown command. Use: test | attend | read | fault | info");
  }
}

void loop() {
  handleSerialCommands();

  bool currentBlackButtonState = digitalRead(BLACK_BUTTON);
  bool currentRedButtonState = digitalRead(RED_BUTTON);
  bool bothButtonsPressed = currentBlackButtonState && currentRedButtonState;

  // --- Logic for Black Button (Passenger Sensor) ---
  if (currentBlackButtonState == HIGH && lastBlackButtonState == LOW) {
    logEvent("PASSENGER", "IN");
  }
  if (currentBlackButtonState == LOW && lastBlackButtonState == HIGH) {
    logEvent("PASSENGER", "OUT");
  }

  // --- Logic to START a Mantrap Incident ---
  if (currentRedButtonState == HIGH && lastRedButtonState == LOW && currentBlackButtonState == HIGH && !alarmActive) {
    alarmActive = true;
    activeIncidentType = "Mantrap";
    logEvent("INCIDENT", "MANTRAP_DETECTED");
    sendAlert(activeIncidentType, "Detected");
  }

  // --- Logic to STOP the alarm with a LONG PRESS ---
  if (alarmActive && bothButtonsPressed) {
    if (resetStartTime == 0) {
      resetStartTime = millis();
      Serial.println("Starting long press timer to silence alarm...");
    } else if (millis() - resetStartTime >= resetDuration) {
      Serial.println("Alarm silenced by local long press.");
      alarmActive = false;
      digitalWrite(LED_PIN, LOW);
      digitalWrite(BUZZER_PIN, HIGH);

      logEvent("INCIDENT_UPDATE", "SILENCED_LOCALLY");
      sendAlert(activeIncidentType, "Attended");

      resetStartTime = 0;
      delay(1000);
    }
  } else {
    if (resetStartTime > 0) {
      Serial.println("Long press cancelled.");
    }
    resetStartTime = 0;
  }

  // --- Handle Active Alarm State (if not stopped) ---
  if (alarmActive) {
    digitalWrite(LED_PIN, HIGH);
    beepBuzzer();
    digitalWrite(LED_PIN, LOW);

    if (millis() - lastStatusCheck > statusCheckInterval) {
      lastStatusCheck = millis();
      checkServerForCommand();
    }
  }

  lastBlackButtonState = currentBlackButtonState;
  lastRedButtonState = currentRedButtonState;

  delay(50);
}

// ===================================================
// ================ FIELD SETUP ======================
// ===================================================
// One firmware for every unit. To configure a device on-site:
//
// 1. Power on a NEW (or factory-reset) device. It creates a WiFi hotspot:
//       SSID: AIM-Lift-Setup     password: aimlift123
// 2. On a phone, join that hotspot. A configuration page opens automatically
//    (if not, browse to http://192.168.4.1).
// 3. Tap "Configure WiFi", pick the site's WiFi and enter its password, then
//    fill in:
//       Device ID  - unique, e.g. ESP32-LIFT-07
//       Lift ID    - MUST match lift_identifier in the database, e.g. WP PMA 80299
//       Premise    - e.g. JKR Ibu Pejabat
// 4. Save. The device reboots, joins the site WiFi and starts reporting.
//
// To change settings later / move the device:
//   Hold BOTH buttons while powering on and keep holding for 3 seconds.
//   This wipes WiFi + Device/Lift/Premise and reopens the setup hotspot.
//
// Serial Monitor (115200) shows the active Device/Lift/Premise on boot and
// "Alert sent, Response: 201" when an incident is posted.
