#include <WiFi.h>
#include <SPI.h>
#include <SD.h>
#include "time.h"
#include <HTTPClient.h>

// ===================================================
// ============== CONFIGURATION ======================
//         👇 UPDATE THESE VALUES 👇
// ===================================================

// ==== WIFI CONFIG ====
const char* ssid     = "mkmk";
const char* password = "mkmk1234";

// ==== SERVER CONFIG ====
// IMPORTANT: Replace with your computer's IP address on the network
const char* serverUrl      = "http://192.168.137.1:8000/api/iot/alert/";
const char* statusCheckUrl = "http://192.168.137.1:8000/api/iot/check_status/";

// ==== DEVICE & PREMISE CONFIG ====
const char* deviceId    = "ESP32-LIFT-01"; // A unique name for this device
const char* premiseName = "JKR Bahagian Perkhidmatan Mekanikal";
const char* liftId      = "WP PMA 80271"; // The specific Lift ID where this device is installed

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
const long  gmtOffset_sec = 0 * 3600; // Malaysia time GMT+8
const int   daylightOffset_sec = 0;

// ==== POLLING CONFIG ====
unsigned long lastStatusCheck = 0;
const long statusCheckInterval = 5000; // Check server every 5 seconds

// ==== SYSTEM STATES ====
bool alarmActive = false;
String activeIncidentType = "";
bool lastBlackButtonState = LOW;
bool lastRedButtonState = LOW;

unsigned long resetStartTime = 0;    // Timer for long press
const long resetDuration = 2000;     // 2000ms = 2 seconds for long press

// SD File
File logFile;

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
    Serial.println("⚠️ Failed to write to lift_log.csv");
  }
}

// ==== HELPER: SEND ALERT TO DJANGO ====
void sendAlert(String type, String status) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverUrl);
    http.addHeader("Content-Type", "application/json");

    String payload = "{\"device_id\":\"" + String(deviceId) + "\","
                     "\"lift_id\":\"" + String(liftId) + "\","
                     "\"incident_type\":\"" + type + "\","
                     "\"premise\":\"" + String(premiseName) + "\","
                     "\"status\":\"" + status + "\"}";

    int httpResponseCode = http.POST(payload);
    if (httpResponseCode > 0) {
      Serial.printf("✅ Alert sent, Response: %d\n", httpResponseCode);
    } else {
      Serial.printf("⚠️ Alert failed, Error: %s\n", http.errorToString(httpResponseCode).c_str());
    }
    http.end();
  }
}

// ==== HELPER: CHECK SERVER FOR COMMAND ====
void checkServerForCommand() {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  String url = String(statusCheckUrl) + "?device_id=" + String(deviceId) + "&incident_type=" + activeIncidentType;
  
  
  
  http.begin(url);
  
  int httpResponseCode = http.GET();
  if (httpResponseCode == 200) {
    String payload = http.getString();
    if (payload.indexOf("\"command\":\"silence\"") > -1) {
      Serial.println("✅ SILENCE command received from server!");
      alarmActive = false;
      digitalWrite(LED_PIN, LOW);
      digitalWrite(BUZZER_PIN, HIGH); // Buzzer OFF
      logEvent("INCIDENT_UPDATE", "SILENCED_REMOTELY");
      sendAlert(activeIncidentType, "Attended");
    }
  } else {
    Serial.printf("⚠️ Status check failed, error: %d\n", httpResponseCode);
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

  Serial.printf("Connecting to %s...", ssid);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println(" ✅ WiFi connected!");

  configTime(gmtOffset_sec, daylightOffset_sec, ntpServer);
  Serial.println("Syncing time with NTP...");
  if (getLocalTime(new struct tm, 5000)) { // 5-second timeout
    Serial.println("✅ Time synced: " + getTimestamp());
  } else {
    Serial.println("⚠️ Failed to sync time");
  }

  if (!SD.begin(SD_CS_PIN)) {
    Serial.println("⚠️ SD Card init failed!");
  } else {
    Serial.println("✅ SD Card ready.");
    logEvent("SYSTEM", "STARTED");
  }
  
  Serial.println("🚀 AIM-Lift Data Logger Ready.");
}

// ==========================================
// ================= LOOP ===================
// ==========================================
void loop() {
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
    activeIncidentType = "Mantrap"; // Changed to Mantrap
    logEvent("INCIDENT", "MANTRAP_DETECTED"); // Updated log message
    sendAlert(activeIncidentType, "Detected");
  }

  // --- Logic to STOP the alarm with a LONG PRESS ---
  if (alarmActive && bothButtonsPressed) {
    if (resetStartTime == 0) {
      resetStartTime = millis();
      Serial.println("Starting long press timer to silence alarm...");
    } else if (millis() - resetStartTime >= resetDuration) {
      Serial.println("✅ Alarm silenced by local long press.");
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