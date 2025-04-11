#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "DHT.h"
#include <Wire.h>
#include <Adafruit_BMP280.h>
#include <SD.h>
#include <SPI.h>

// WiFi Credentials
const char* ssid = "Xperia";
const char* password = "8765432191";

// MQTT HiveMQ Cloud
const char* mqtt_server = "874c8249bd8b49bf822b11e8975874c6.s1.eu.hivemq.cloud";
const int mqtt_port = 8883;
const char* mqtt_user = "Rameez";
const char* mqtt_password = "PassWord5$";
const char* mqtt_topic_sensor = "coldchain/truck1/sensor1";
const char* mqtt_topic_gpswifi = "coldchain/truck1/sensor1/location";

// Hardware Pins
#define DHTPIN 27
#define MQ135PIN 35
#define LDRPIN 26
#define VIBRATIONPIN 34
#define DHTTYPE DHT22
#define SD_CS_PIN 5
#define BUFFER_SIZE 100

WiFiClientSecure espClient;
PubSubClient client(espClient);
DHT dht(DHTPIN, DHTTYPE);
Adafruit_BMP280 bmp;
File sdFile;

// Buffer Struct
struct SensorData {
  String json;
  bool sent;
};
SensorData buffer[BUFFER_SIZE];
int bufferIndex = 0;

volatile bool vibrationDetected = false;
bool internetAvailable = false;
unsigned long lastWifiScan = 0;
const unsigned long wifiScanInterval = 60000; // 1 minute
unsigned long lastGPSTime = 0;
const unsigned long gpsInterval = 30000; // 30 seconds

void IRAM_ATTR vibrationISR() {
  vibrationDetected = true;
}

void setup_wifi() {
  Serial.print("Connecting to WiFi...");
  WiFi.begin(ssid, password);
  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 20) {
    delay(500);
    Serial.print(".");
    retries++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nConnected to WiFi!");
    internetAvailable = true;
  } else {
    Serial.println("\nWiFi connection failed.");
    internetAvailable = false;
  }
}

void reconnect() {
  if (!internetAvailable) return;
  while (!client.connected()) {
    Serial.print("Connecting to MQTT...");
    if (client.connect("ESP32Truck1", mqtt_user, mqtt_password)) {
      Serial.println("connected!");
    } else {
      Serial.print("failed, rc=");
      Serial.print(client.state());
      Serial.println(" retrying in 5s...");
      delay(5000);
    }
  }
}

void storeToSD(String data) {
  sdFile = SD.open("data_log.txt", FILE_APPEND);
  if (sdFile) {
    sdFile.println(data);
    sdFile.close();
  }
}

void sendToHiveMQ(String jsonData, const char* topic, bool bufferIfFail = true) {
  if (client.connected()) {
    if (client.publish(topic, jsonData.c_str())) {
      Serial.println("Sent to topic [" + String(topic) + "]: " + jsonData);
    } else {
      Serial.println("MQTT publish failed.");
      if (bufferIfFail) {
        if (bufferIndex < BUFFER_SIZE) {
          buffer[bufferIndex++] = {jsonData, false};
        } else {
          storeToSD(jsonData);
        }
      } else {
        Serial.println("Dropped (No buffer): " + jsonData);
      }
    }
  } else {
    Serial.println("MQTT disconnected.");
    if (bufferIfFail) {
      if (bufferIndex < BUFFER_SIZE) {
        buffer[bufferIndex++] = {jsonData, false};
      } else {
        storeToSD(jsonData);
      }
    } else {
      Serial.println("Dropped (No buffer): " + jsonData);
    }
  }
}

void processBufferedData() {
  for (int i = 0; i < bufferIndex; i++) {
    if (!buffer[i].sent) {
      sendToHiveMQ(buffer[i].json, mqtt_topic_sensor, true);
      buffer[i].sent = true;
    }
  }
  bufferIndex = 0;
}

void sendFromSD() {
  sdFile = SD.open("data_log.txt", FILE_READ);
  if (sdFile) {
    while (sdFile.available()) {
      String line = sdFile.readStringUntil('\n');
      sendToHiveMQ(line, mqtt_topic_sensor, true);
    }
    sdFile.close();
    SD.remove("data_log.txt");
  }
}

void scanWiFiNetworks(JsonDocument& jsonDoc) {
  int n = WiFi.scanNetworks();
  JsonArray wifiArr = jsonDoc.createNestedArray("wifiNetworks");
  for (int i = 0; i < min(n, 2); i++) {
    JsonObject net = wifiArr.createNestedObject();
    net["macAddress"] = WiFi.BSSIDstr(i);
    net["signalStrength"] = WiFi.RSSI(i);
  }
  WiFi.scanDelete();
}

void setup() {
  Serial.begin(115200);
  setup_wifi();
  espClient.setInsecure(); // TLS without validation
  client.setServer(mqtt_server, mqtt_port);

  dht.begin();
  pinMode(LDRPIN, INPUT);
  pinMode(VIBRATIONPIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(VIBRATIONPIN), vibrationISR, FALLING);

  if (!bmp.begin(0x76)) {
    Serial.println("BMP280 not found!");
    while (1);
  }

  if (!SD.begin(SD_CS_PIN)) {
    Serial.println("SD card failed!");
  }

  Serial.println("ESP32 Cold Chain Ready!");
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    internetAvailable = false;
    setup_wifi();
  } else {
    internetAvailable = true;
  }

  if (internetAvailable) {
    reconnect();
    processBufferedData();
    sendFromSD();
  }

  // SENSOR DATA EVERY 5 SECONDS
  float temp = dht.readTemperature();
  float humidity = dht.readHumidity();
  int airQuality = analogRead(MQ135PIN);
  int light = digitalRead(LDRPIN);
  String lightStatus = (light == 0) ? "Bright" : "Dark";
  String vibrationStatus = vibrationDetected ? "Vibration Detected" : "No Vibration";
  vibrationDetected = false;
  float bmpTemp = bmp.readTemperature();
  float pressure = bmp.readPressure() / 100.0;
  float altitude = bmp.readAltitude(1013.25);

  StaticJsonDocument<512> sensorDoc;
  sensorDoc["sensor_id"] = "sensor1";
  sensorDoc["temperature"] = temp;
  sensorDoc["humidity"] = humidity;
  sensorDoc["airQuality"] = airQuality;
  sensorDoc["light"] = lightStatus;
  sensorDoc["vibration"] = vibrationStatus;
  sensorDoc["bmp_temperature"] = bmpTemp;
  sensorDoc["pressure"] = pressure;
  sensorDoc["altitude"] = altitude;

  char sensorData[512];
  serializeJson(sensorDoc, sensorData);
  sendToHiveMQ(sensorData, mqtt_topic_sensor, true);

  // GPS + WIFI every 30 seconds
  if (millis() - lastGPSTime >= gpsInterval) {
    lastGPSTime = millis();
    StaticJsonDocument<256> gpsWifiDoc;
    gpsWifiDoc["sensor_id"] = "sensor1";

    // Placeholder GPS data
    gpsWifiDoc["latitude"] = "-";
    gpsWifiDoc["longitude"] = "-";

    scanWiFiNetworks(gpsWifiDoc);

    char gpsWifiData[256];
    serializeJson(gpsWifiDoc, gpsWifiData);
    sendToHiveMQ(gpsWifiData, mqtt_topic_gpswifi, false);
  }

  delay(5000);
}
