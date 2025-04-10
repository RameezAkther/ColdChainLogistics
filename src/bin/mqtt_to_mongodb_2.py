import json
import time
import pymongo
import paho.mqtt.client as mqtt
import requests
from datetime import datetime, timedelta
from threading import Timer
import ssl  # Added for SSL/TLS support

# MongoDB Connection
mongo_client = pymongo.MongoClient("mongodb://localhost:27017/")
db = mongo_client["ColdChainDB"]
sensor_status_collection = db["sensor_status"]
alerts_collection = db["alerts_collection"]
users_collection = db["users"]  
sensor_thresholds_collection = db["sensor_thresholds"]
sensor_control_collection = db["sensor_control"]

# HiveMQ Cloud Credentials
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPICS = [("coldchain/truck1/sensor1", 0), ("coldchain/truck1/sensor1/location", 0)]


# Cooldown Period (in seconds)
ALERT_COOLDOWN = 60  # 1 minute

# Dictionary to track last received timestamps
last_received_time = {}

# Timeout interval to consider a sensor offline
TIMEOUT_INTERVAL = 10  # seconds

# Telegram Bot Token
TELEGRAM_BOT_TOKEN = "7801773734:AAG69gRWh9mqKZxJmmF8aIFycD-bKig2Gpo"

def get_thresholds(sensor_id):
    thresholds_doc = sensor_thresholds_collection.find_one({"sensor_id": sensor_id})
    if thresholds_doc:
        return thresholds_doc.get("thresholds", {})
    return {}

# 🔹 Function to send a Telegram message
def send_telegram_alert(chat_id, sensor_id, alert_message):
    if chat_id:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {"chat_id": chat_id, "text": f"🚨 Alert from {sensor_id}:\n{alert_message}"}
            response = requests.post(url, json=data)
            print(f"Telegram Alert Sent to {chat_id}: {response.json()}")
        except Exception as e:
            print(f"Error sending Telegram alert: {e}")

# 🔹 Check if an alert should be sent based on cooldown and new alert types
def should_send_alert(sensor_id, new_alerts):
    last_alert = alerts_collection.find_one({"sensor_id": sensor_id}, {"last_alert_time": 1, "last_alert_type": 1})

    if last_alert:
        last_alert_time = last_alert.get("last_alert_time")
        last_alert_type = last_alert.get("last_alert_type", [])

        # If cooldown is still active
        if last_alert_time and datetime.utcnow() - last_alert_time < timedelta(seconds=ALERT_COOLDOWN):
            # Check if new alerts are different from last alerted types
            if any(alert not in last_alert_type for alert in new_alerts):
                return True  # Override cooldown if a new alert type appears
            return False  # Otherwise, respect cooldown
    return True  # No recent alert, send a new one

# 🔹 Function to check enabled sensors
def get_enabled_sensors(sensor_id):
    sensor_doc = sensor_control_collection.find_one({"sensor_id": sensor_id})
    if sensor_doc:
        return {k: v["status"] for k, v in sensor_doc.get("sensors", {}).items()}
    return {}

# MQTT Callback - When connected
def on_connect(client, userdata, flags, rc):
    print("Connected to MQTT Broker")
    client.subscribe(MQTT_TOPICS)


# MQTT Callback - When a message is received
def on_message(client, userdata, msg):
    global last_received_time

    try:
        payload = json.loads(msg.payload.decode())
        print(f"📦 Raw payload: {payload}")

        topic_parts = msg.topic.split('/')
        sensor_id = topic_parts[2] if len(topic_parts) >= 3 else payload.get("sensor_id", "sensor1")
        payload["sensor_id"] = sensor_id
        payload["timestamp"] = datetime.utcnow()

        # --- Topic: coldchain/truck1/sensor1 (Sensor Data) ---
        if msg.topic == "coldchain/truck1/sensor1":
            # Normalize missing fields
            payload.setdefault("temperature", 0)
            payload.setdefault("humidity", 0)
            payload.setdefault("airQuality", 0)
            payload.setdefault("light", "Unknown")
            payload.setdefault("vibration", "No Vibration")
            payload.setdefault("bmp_temperature", 0)
            payload.setdefault("pressure", 0)
            payload.setdefault("altitude", 0)

            # Apply sensor ON/OFF controls
            sensor_control = sensor_control_collection.find_one({"sensor_id": sensor_id})
            if not sensor_control:
                print(f"⚠️ Sensor {sensor_id} not found in control DB.")
                return

            active_sensors = {s: v["status"] for s, v in sensor_control["sensors"].items()}
            if active_sensors.get("dht22", "ON") == "OFF":
                payload["temperature"] = 0
                payload["humidity"] = 0
            if active_sensors.get("mq135", "ON") == "OFF":
                payload["airQuality"] = 0
            if active_sensors.get("bmp280", "ON") == "OFF":
                payload["pressure"] = 0
                payload["altitude"] = 0
                payload["bmp_temperature"] = 0
            if active_sensors.get("lm393", "ON") == "OFF":
                payload["light"] = "OFF"
            if active_sensors.get("sw420", "ON") == "OFF":
                payload["vibration"] = "OFF"

            # Update last seen
            last_received_time[sensor_id] = time.time()
            sensor_status_collection.update_one(
                {"sensor_id": sensor_id},
                {"$set": {"status": "online", "last_seen": payload["timestamp"]}},
                upsert=True
            )

            # Save to `sensor1` collection
            db[sensor_id].insert_one(payload)
            print(f"✅ Sensor data saved in {sensor_id}: {payload}")

            # --- Alert Logic ---
            thresholds = get_thresholds(sensor_id)
            TEMP_THRESHOLD = float(thresholds.get("dht22", {}).get("temperature", 36))
            HUMIDITY_THRESHOLD = float(thresholds.get("dht22", {}).get("humidity", 80))
            GAS_THRESHOLD = float(thresholds.get("mq135", {}).get("gas", 2000))

            alerts = []
            if payload["temperature"] > TEMP_THRESHOLD:
                alerts.append(f"High Temperature: {payload['temperature']}°C")
            if payload["humidity"] > HUMIDITY_THRESHOLD:
                alerts.append(f"High Humidity: {payload['humidity']}%")
            if payload["airQuality"] > GAS_THRESHOLD:
                alerts.append(f"High Gas: {payload['airQuality']} PPM")
            if payload["vibration"] == "Vibration Detected":
                alerts.append("Vibration Detected")
            if payload["light"] == "Bright":
                alerts.append("Bright Light Detected")

            if alerts and should_send_alert(sensor_id, alerts):
                alert_msg = "\n".join(alerts)

                alerts_collection.update_one(
                    {"sensor_id": sensor_id},
                    {
                        "$push": {"logs": {"timestamp": payload["timestamp"], "alerts": alerts}},
                        "$set": {
                            "last_alert_time": datetime.utcnow(),
                            "last_alert_type": alerts
                        }
                    },
                    upsert=True
                )

                users = users_collection.find({"device_id": sensor_id})
                for user in users:
                    chat_id = user.get("chat_id")
                    if chat_id:
                        send_telegram_alert(chat_id, sensor_id, alert_msg)

        # --- Topic: coldchain/truck1/sensor1/location (GPS + WiFi) ---
        elif msg.topic == "coldchain/truck1/sensor1/location":
            # Handle "-" or missing GPS
            try:
                payload["gps_lat"] = float(payload.get("gps_lat", 0)) if payload.get("gps_lat") not in ["-", "", None] else 0
            except:
                payload["gps_lat"] = 0
            try:
                payload["gps_lng"] = float(payload.get("gps_lng", 0)) if payload.get("gps_lng") not in ["-", "", None] else 0
            except:
                payload["gps_lng"] = 0

            payload.setdefault("wifiAccessPoints", [])

            db[f"{sensor_id}_location"].insert_one(payload)
            print(f"📍 Location data saved in {sensor_id}_location: {payload}")

    except Exception as e:
        print(f"❌ Error processing message: {e}")

# 🔹 Check sensor status periodically
def check_offline_sensors():
    global last_received_time

    current_time = time.time()
    for sensor_id, last_time in last_received_time.items():
        if current_time - last_time > TIMEOUT_INTERVAL:
            sensor_status_collection.update_one(
                {"sensor_id": sensor_id},
                {"$set": {"status": "offline"}},
                upsert=True
            )
            print(f"{sensor_id} marked as offline")

    # Schedule the next check
    Timer(TIMEOUT_INTERVAL, check_offline_sensors).start()

# Initialize MQTT Client with HiveMQ Cloud configuration
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

# Set username and password for HiveMQ Cloud
#client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

# Configure SSL/TLS for secure connection
#client.tls_set(tls_version=ssl.PROTOCOL_TLS)  # Enable SSL/TLS support

client.connect(MQTT_BROKER, MQTT_PORT, 60)

# Start checking offline sensors
check_offline_sensors()

# Start MQTT loop
client.loop_forever()