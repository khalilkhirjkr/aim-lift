// =====================================================================
//  AIM-Lift trigger node  +  2.8" ILI9341 status screen (demo build)
// ---------------------------------------------------------------------
//  This is the button/WiFi/alert firmware with a status display bolted
//  on. The two physical buttons still do everything on their own, so
//  the screen is pure upside: if touch or the panel misbehaves, pull
//  the screen power and the demo is unaffected.
//
//  ROLLBACK: re-flash sketch_aug15a_trigger_20251024 for the plain
//  button-only rig.
//
//  LIBRARIES (Library Manager):
//    - Adafruit GFX Library
//    - Adafruit ILI9341
//    - XPT2046_Touchscreen   (by Paul Stoffregen)
//    - WiFiManager (tzapu), Preferences  (as before)
//
//  WIRING  (red "2.8 TFT 240x320 V1.1" board  ->  ESP32 devkit)
//    VCC -> 3V3        LED -> 3V3 (backlight always on)
//    GND -> GND        SDO/MISO -> GPIO19
//    CS  -> GPIO15     SCK      -> GPIO18
//    RESET -> GPIO4    SDI/MOSI -> GPIO23
//    DC  -> GPIO2
//    T_CS  -> GPIO21   T_CLK -> GPIO18 (shared)
//    T_DIN -> GPIO23 (shared)   T_DO -> GPIO19 (shared)   T_IRQ -> (leave open)
//    The board's SD_* pins on the right edge: leave unconnected.
//
//    Button modules (VCC/OUT/GND):  OUT -> GPIO27 (BLACK) / GPIO26 (RED),
//                                   VCC -> 3V3, GND -> GND. Default ACTIVE-LOW.
//                                   (swap these two #defines if the buttons feel reversed)
//    Buzzer module (VCC/I-O/GND):    I-O -> GPIO25, VCC -> 3V3, GND -> GND. Default ACTIVE-LOW.
//    Status LED:  GPIO32 (+220R) -> GND.  Onboard GPIO2 LED is now the TFT DC line.
//    Polarity wrong? flip BUTTONS_ACTIVE_HIGH / BUZZER_ACTIVE_HIGH and re-flash.
// =====================================================================

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <WiFiManager.h>
#include <Preferences.h>
#include <SPI.h>
#include <SD.h>
#include "time.h"
#include <HTTPClient.h>

#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <XPT2046_Touchscreen.h>

// ===================================================
// ============== CONFIGURATION ======================
// ===================================================
const char* serverUrl      = "https://aim-lift.onrender.com/api/iot/alert/";
const char* statusCheckUrl = "https://aim-lift.onrender.com/api/iot/check_status/";
const char* readingUrl     = "https://aim-lift.onrender.com/api/iot/reading/";
const char* deviceKey      = "REPLACE_WITH_IOT_DEVICE_KEY";

const char* setupApName = "AIM-Lift-Setup";
const char* setupApPass = "aimlift123";

String deviceId    = "ESP32-LIFT-01";
String premiseName = "";
String liftId      = "";

// ==== PIN SETUP ====
#define BLACK_BUTTON 27   // passenger weight sensor (stand-in)  [OUT -> GPIO27]
#define RED_BUTTON   26   // emergency button (stand-in)         [OUT -> GPIO26]

// 3-pin button modules (VCC / OUT / GND): most are ACTIVE-LOW (OUT idles HIGH,
// goes LOW when pressed). If the polarity test shows an alarm at rest, set this
// to 1 and re-flash.
#define BUTTONS_ACTIVE_HIGH 0
#if BUTTONS_ACTIVE_HIGH
  #define BTN_MODE     INPUT_PULLDOWN
  #define BTN_PRESSED  HIGH
#else
  #define BTN_MODE     INPUT_PULLUP
  #define BTN_PRESSED  LOW
#endif
inline bool btnDown(int pin) { return digitalRead(pin) == BTN_PRESSED; }
#define LED_PIN      32   // moved off GPIO2 (TFT DC lives there now)
#define BUZZER_PIN   25   // 3-pin active buzzer module (VCC / I-O / GND)
// Most active buzzer modules are ACTIVE-LOW. If yours sounds continuously at
// rest, set this to 1 and re-flash.
#define BUZZER_ACTIVE_HIGH 0
#if BUZZER_ACTIVE_HIGH
  #define BUZZ_ON  HIGH
  #define BUZZ_OFF LOW
#else
  #define BUZZ_ON  LOW
  #define BUZZ_OFF HIGH
#endif
#define SD_CS_PIN    5    // unused in the screen build (screen SD not wired)

// ==== TFT + TOUCH PINS ====
#define TFT_CS   15
#define TFT_DC    2
#define TFT_RST   4
#define TOUCH_CS 21

Adafruit_ILI9341 tft = Adafruit_ILI9341(TFT_CS, TFT_DC, TFT_RST);
XPT2046_Touchscreen ts(TOUCH_CS);

// Panel orientation: 0 & 2 = portrait (240x320), 1 & 3 = landscape (320x240).
// The screen layout adapts to whatever you pick. Don't want to re-flash to
// find it? Type "rot" in the Serial Monitor to cycle 0->1->2->3 live, then
// set this to the value it prints.
#define SCREEN_ROTATION 0   // 0/2 = portrait, 1/3 = landscape. Type "rot" in Serial
                            // to cycle live; stop at the value with NO noise band,
                            // text upright, footer at the bottom. Then set it here.

// 16-bit 565 colours  (monochrome, matching the approved mock-up)
#define C_BG      0x0000   // black
#define C_INK     0xFFFF   // white
#define C_MUTED   0x8C71   // grey (tagline / footer)

// ===================================================
const char* ntpServer = "pool.ntp.org";
const long  gmtOffset_sec = 8 * 3600;
const int   daylightOffset_sec = 0;

unsigned long lastStatusCheck = 0;
const long statusCheckInterval = 5000;

bool alarmActive = false;      // emergency channel (RED button / Mantrap)
bool sysHealthy  = true;       // predictive channel (set from /reading/ verdict)
String activeIncidentType = "";
bool lastBlackDown = false;
bool lastRedDown = false;

unsigned long resetStartTime = 0;
const long resetDuration = 2000;
bool silenceArmed = false;     // both buttons must be released after an alarm before a 2s hold silences it

// on-screen ATTEND (touch anywhere while in alarm)
unsigned long touchDownAt = 0;
bool touchLatched = false;
const long touchHoldMs = 350;

String lastEventLine = "Sedia";

// forward declarations (screen helpers call these before they are defined)
void sendAlert(String type, String status);
void sendReading(bool abnormal);
void screenStatus();
String clockHHMM();

File logFile;
Preferences prefs;
bool shouldSaveConfig = false;
void saveConfigCallback() { shouldSaveConfig = true; }

// ==== CONFIG PERSISTENCE ====
void loadConfig() {
  prefs.begin("aimlift", true);
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

void maybeFactoryReset() {
  if (btnDown(BLACK_BUTTON) && btnDown(RED_BUTTON)) {
    Serial.println("Both buttons held - keep holding 3s to clear config...");
    unsigned long t0 = millis();
    while (btnDown(BLACK_BUTTON) && btnDown(RED_BUTTON)) {
      if (millis() - t0 > 3000) {
        WiFiManager wm;
        wm.resetSettings();
        prefs.begin("aimlift", false);
        prefs.clear();
        prefs.end();
        Serial.println("Config cleared. Restarting...");
        delay(500);
        ESP.restart();
      }
      delay(50);
    }
  }
}

String getTimestamp() {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) return "TIME_ERROR";
  char buffer[30];
  strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", &timeinfo);
  return String(buffer);
}

String clockHHMM() {
  struct tm t;
  if (!getLocalTime(&t)) return "--:--";
  char b[6];
  strftime(b, sizeof(b), "%H:%M", &t);
  return String(b);
}

void logEvent(String eventCategory, String eventDetail) {
  String timestamp = getTimestamp();
  String logLine = timestamp + "," + eventCategory + "," + eventDetail;
  logFile = SD.open("/lift_log.csv", FILE_APPEND);
  if (logFile) {
    logFile.println(logLine);
    logFile.close();
    Serial.println("LOGGED: " + logLine);
  } else {
    Serial.println("Failed to write to lift_log.csv");
  }
}

// =====================================================================
// ============================ SCREEN =================================
// =====================================================================
// Monochrome white-on-black, matches the approved mock-up. Works in any rotation.

String dateDMY() {
  struct tm t;
  if (!getLocalTime(&t)) return "--";
  char b[16];
  strftime(b, sizeof(b), "%d %b %Y", &t);   // e.g. 06 Sep 2026
  return String(b);
}

void printCentred(const char* txt, int y, uint8_t size, uint16_t colour) {
  int16_t x1, y1; uint16_t w, h;
  tft.setTextSize(size);
  tft.setTextColor(colour);
  tft.getTextBounds(txt, 0, 0, &x1, &y1, &w, &h);
  int x = ((int)tft.width() - (int)w) / 2; if (x < 0) x = 0;
  tft.setCursor(x, y);
  tft.print(txt);
}

// AIM-Lift mark: rounded square outline + two vertical "door" pills
void drawLogo(int x, int y, int s) {
  int r = s / 4;
  tft.drawRoundRect(x,     y,     s,     s,     r,     C_INK);
  tft.drawRoundRect(x + 1, y + 1, s - 2, s - 2, r - 1, C_INK);
  tft.drawRoundRect(x + 2, y + 2, s - 4, s - 4, r - 1, C_INK);
  int pw = s / 6; if (pw < 3) pw = 3;
  int ph = s * 3 / 5;
  int py = y + (s - ph) / 2;
  int cx = x + s / 2;
  int gap = s / 10;
  tft.fillRoundRect(cx - gap - pw, py, pw, ph, pw / 2, C_INK);
  tft.fillRoundRect(cx + gap,      py, pw, ph, pw / 2, C_INK);
}

// One layout for every rotation: header pinned to the top, footer pinned to the
// bottom, status centred between. Fits inside a 240 x 240 safe area so it never
// clips whether the panel is 240x320 or 320x240.
void drawScreen(const char* line1, const char* bigWord) {
  int W = tft.width(), H = tft.height();
  int cx = W / 2;
  tft.fillScreen(C_BG);

  // header (top)
  drawLogo(cx - 15, 12, 30);
  printCentred("AIM-Lift", 48, 3, C_INK);
  printCentred("Smart Lift Monitoring", 76, 1, C_MUTED);

  // status (vertically centred)
  printCentred(line1, H / 2 - 26, 3, C_INK);
  printCentred(bigWord, H / 2 + 6, 4, C_INK);

  // footer (bottom): dot + "Online 07 Sep 2026"
  String line = "Online " + dateDMY();
  tft.setTextSize(2);
  int16_t x1, y1; uint16_t tw, th;
  tft.getTextBounds(line.c_str(), 0, 0, &x1, &y1, &tw, &th);
  int fx = cx - (10 + (int)tw) / 2; if (fx < 2) fx = 2;
  int fy = H - 26;
  tft.fillCircle(fx + 4, fy + 6, 4, C_INK);
  tft.setTextColor(C_MUTED);
  tft.setCursor(fx + 14, fy);
  tft.print(line);
}

void screenSplash(const char* line) {
  int W = tft.width(), H = tft.height();
  tft.fillScreen(C_BG);
  drawLogo(W / 2 - 20, H / 2 - 60, 40);
  printCentred("AIM-Lift", H / 2 - 6, 3, C_INK);
  printCentred(line, H / 2 + 30, 1, C_MUTED);
}

// UNHEALTHY when an emergency alarm is active OR the predictive channel has
// flagged a fault; HEALTHY otherwise.
void screenStatus() {
  bool bad = alarmActive || !sysHealthy;
  drawScreen("Lift Status", bad ? "UNHEALTHY" : "HEALTHY");
}

// touch anywhere, held briefly, while in alarm -> attend on-site
void touchAttendCheck() {
  bool down = ts.touched();
  if (down && !alarmActive) { touchDownAt = 0; return; }

  if (down && alarmActive) {
    if (touchDownAt == 0) touchDownAt = millis();
    if (!touchLatched && millis() - touchDownAt >= touchHoldMs) {
      touchLatched = true;
      Serial.println("Screen touch -> attend");
      alarmActive = false;
      digitalWrite(LED_PIN, LOW);
      digitalWrite(BUZZER_PIN, BUZZ_OFF);
      logEvent("INCIDENT_UPDATE", "SILENCED_TOUCH");
      sendAlert(activeIncidentType, "Attended");
      lastEventLine = "Dihadiri " + clockHHMM();
      screenStatus();
    }
  } else {
    touchDownAt = 0;
    touchLatched = false;
  }
}

// =====================================================================
void sendAlert(String type, String status) {
  if (WiFi.status() == WL_CONNECTED) {
    WiFiClientSecure client;
    client.setInsecure();
    HTTPClient http;
    http.begin(client, serverUrl);
    http.setConnectTimeout(15000);
    http.setTimeout(60000);
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

void sendReading(bool abnormal) {
  if (WiFi.status() != WL_CONNECTED) { Serial.println("No WiFi."); return; }

  float p1 = random(2970, 3010) / 10.0;
  float p2 = random(3080, 3095) / 10.0;
  float p3 = random(1450, 1550);
  float s1 = random(35, 45);
  float s2 = random(10, 150);
  float s3 = random(10, 80);
  float vib  = abnormal ? random(200, 500) / 10.0 : random(1, 30) / 10.0;
  float vacc = random(1, 15) / 100.0;
  float ac   = abnormal ? random(800, 1000) / 10.0 : random(550, 630) / 10.0;

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
  String resp = (code > 0) ? http.getString() : "";
  if (code > 0) {
    Serial.printf("Reading sent (%s), Response: %d\n", abnormal ? "fault" : "normal", code);
    Serial.println(resp);
  } else {
    Serial.printf("Reading failed, Error: %s\n", http.errorToString(code).c_str());
  }
  http.end();

  // ---- drive the HEALTHY / UNHEALTHY screen ----
  if (code == 201) {
    resp.replace(" ", "");                       // "incident_opened": true -> :true
    sysHealthy = (resp.indexOf("\"incident_opened\":true") == -1);
  } else {
    sysHealthy = !abnormal;   // no server verdict (e.g. key not set) - mirror the command so the demo still shows
  }
  screenStatus();
}

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
      digitalWrite(BUZZER_PIN, BUZZ_OFF);
      logEvent("INCIDENT_UPDATE", "SILENCED_REMOTELY");
      sendAlert(activeIncidentType, "Attended");
      lastEventLine = "Dihadiri (jauh) " + clockHHMM();
      screenStatus();
    }
  } else {
    Serial.printf("Status check failed, error: %d\n", httpResponseCode);
  }
  http.end();
}

void beepBuzzer() {
  digitalWrite(BUZZER_PIN, BUZZ_ON);
  delay(150);
  digitalWrite(BUZZER_PIN, BUZZ_OFF);
  delay(150);
}

// ==========================================
void setup() {
  Serial.begin(115200);

  pinMode(BLACK_BUTTON, BTN_MODE);
  pinMode(RED_BUTTON, BTN_MODE);
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  digitalWrite(BUZZER_PIN, BUZZ_OFF);

  // ---- screen up first so there is always something on the panel ----
  tft.begin();                        // sets up SPI itself (VSPI: SCK18 MISO19 MOSI23)
  tft.setRotation(SCREEN_ROTATION);
  tft.fillScreen(C_BG);
  ts.begin();
  ts.setRotation(SCREEN_ROTATION);
  Serial.printf("SCREEN build v2 | rotation %d | panel %d x %d\n",
                SCREEN_ROTATION, tft.width(), tft.height());
  screenSplash("Connecting...");

  loadConfig();
  maybeFactoryReset();

  WiFiManager wm;
  WiFiManagerParameter p_device("device", "Device ID", deviceId.c_str(), 40);
  WiFiManagerParameter p_lift("lift", "Lift ID (must match lift_identifier in DB)", liftId.c_str(), 60);
  WiFiManagerParameter p_premise("premise", "Premise name", premiseName.c_str(), 100);
  wm.addParameter(&p_device);
  wm.addParameter(&p_lift);
  wm.addParameter(&p_premise);
  wm.setSaveConfigCallback(saveConfigCallback);
  wm.setConfigPortalTimeout(180);

  Serial.printf("Starting WiFi. If unconfigured, join AP \"%s\" (pass: %s)\n", setupApName, setupApPass);
  screenSplash("Setup Wi-Fi: AIM-Lift-Setup");
  if (!wm.autoConnect(setupApName, setupApPass)) {
    Serial.println("WiFi connect / portal timed out. Restarting...");
    screenSplash("Wi-Fi failed - restarting");
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
  if (getLocalTime(&ti, 5000)) Serial.println("Time synced: " + getTimestamp());
  else Serial.println("Failed to sync time");

  if (!SD.begin(SD_CS_PIN)) {
    Serial.println("SD Card init failed (expected in the screen build).");
  } else {
    Serial.println("SD Card ready.");
    logEvent("SYSTEM", "STARTED");
  }

  lastEventLine = "Sedia " + clockHHMM();
  screenStatus();
  Serial.println("AIM-Lift screen node ready.");
}

// ==========================================
// Serial test commands: test | attend | read | fault | rot | info
void handleSerialCommands() {
  if (!Serial.available()) return;
  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  if (cmd == "test") {
    Serial.println(">> Sending test alert (Mantrap / Detected)...");
    alarmActive = true; silenceArmed = false; activeIncidentType = "Mantrap";
    lastEventLine = "Mantrap " + clockHHMM();
    screenStatus();
    sendAlert("Mantrap", "Detected");
  } else if (cmd == "attend") {
    Serial.println(">> Sending test alert (Mantrap / Attended)...");
    alarmActive = false;
    digitalWrite(LED_PIN, LOW); digitalWrite(BUZZER_PIN, BUZZ_OFF);
    lastEventLine = "Dihadiri " + clockHHMM();
    screenStatus();
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
  } else if (cmd == "rot") {
    static int r = SCREEN_ROTATION;
    r = (r + 1) % 4;
    tft.setRotation(r);
    ts.setRotation(r);
    screenStatus();
    Serial.printf(">> rotation = %d | panel %d x %d  --> set #define SCREEN_ROTATION and re-flash\n",
                  r, tft.width(), tft.height());
  } else if (cmd.length()) {
    Serial.println(">> Unknown command. Use: test | attend | read | fault | rot | info");
  }
}

void loop() {
  handleSerialCommands();
  touchAttendCheck();

  bool blackDown = btnDown(BLACK_BUTTON);
  bool redDown   = btnDown(RED_BUTTON);
  bool bothButtonsPressed = blackDown && redDown;

  // --- button debug: prints only when a button changes state ---
  if (blackDown != lastBlackDown) Serial.printf("BLACK %s\n", blackDown ? "DOWN" : "up");
  if (redDown   != lastRedDown)   Serial.printf("RED   %s\n", redDown   ? "DOWN" : "up");

  if (blackDown && !lastBlackDown) logEvent("PASSENGER", "IN");
  if (!blackDown && lastBlackDown) logEvent("PASSENGER", "OUT");

  // START a Mantrap incident
  if (redDown && !lastRedDown && blackDown && !alarmActive) {
    alarmActive = true;
    silenceArmed = false;          // must release both buttons before the 2s-silence works
    activeIncidentType = "Mantrap";
    logEvent("INCIDENT", "MANTRAP_DETECTED");
    lastEventLine = "Mantrap " + clockHHMM();
    screenStatus();
    sendAlert(activeIncidentType, "Detected");
  }

  // Arm the long-press silence only after both buttons have been released once,
  // so "hold BLACK + press RED and keep holding" just raises the alarm.
  if (alarmActive && !bothButtonsPressed) silenceArmed = true;

  // STOP the alarm with a LONG PRESS of both buttons (once armed)
  if (alarmActive && bothButtonsPressed && silenceArmed) {
    if (resetStartTime == 0) {
      resetStartTime = millis();
      Serial.println("Starting long press timer to silence alarm...");
    } else if (millis() - resetStartTime >= resetDuration) {
      Serial.println("Alarm silenced by local long press.");
      alarmActive = false;
      digitalWrite(LED_PIN, LOW);
      digitalWrite(BUZZER_PIN, BUZZ_OFF);
      logEvent("INCIDENT_UPDATE", "SILENCED_LOCALLY");
      lastEventLine = "Dihadiri " + clockHHMM();
      screenStatus();
      sendAlert(activeIncidentType, "Attended");
      resetStartTime = 0;
      delay(1000);
    }
  } else {
    if (resetStartTime > 0) Serial.println("Long press cancelled.");
    resetStartTime = 0;
  }

  if (alarmActive) {
    digitalWrite(LED_PIN, HIGH);
    beepBuzzer();
    digitalWrite(LED_PIN, LOW);

    if (millis() - lastStatusCheck > statusCheckInterval) {
      lastStatusCheck = millis();
      checkServerForCommand();
    }
  }

  lastBlackDown = blackDown;
  lastRedDown = redDown;

  delay(50);
}
