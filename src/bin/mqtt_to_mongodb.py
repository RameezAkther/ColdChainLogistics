import json
import time
import pymongo
import paho.mqtt.client as mqtt
import requests
from datetime import datetime, timedelta
from threading import Timer

# MongoDB Connection
mongo_client = pymongo.MongoClient("mongodb://localhost:27017/")
db = mongo_client["ColdChainDB"]
sensor_status_collection = db["sensor_status"]
alerts_collection = db["alerts_collection"]
users_collection = db["users"]  
sensor_thresholds_collection = db["sensor_thresholds"]
sensor_control_collection = db["sensor_control"]

# MQTT Broker Config
MQTT_BROKER = "192.168.234.91"
MQTT_PORT = 1883
MQTT_TOPIC = "coldchain/truck1/sensor1"

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

# 🔹 Function to get sensor thresholds from MongoDB
# def get_thresholds(device_id):
#     thresholds_doc = thresholds_collection.find_one({"device_id": device_id})
#     if thresholds_doc:
#         return thresholds_doc.get("thresholds", {})
#     return {}

# 🔹 Function to check enabled sensors
def get_enabled_sensors(sensor_id):
    sensor_doc = sensor_control_collection.find_one({"sensor_id": sensor_id})
    if sensor_doc:
        return {k: v["status"] for k, v in sensor_doc.get("sensors", {}).items()}
    return {}

# MQTT Callback - When connected
def on_connect(client, userdata, flags, rc):
    print("Connected to MQTT Broker")
    client.subscribe(MQTT_TOPIC)

# MQTT Callback - When a message is received
def on_message(client, userdata, msg):
    global last_received_time

    try:
        payload = json.loads(msg.payload.decode())
        sensor_id = payload.get("sensor_id", "unknown_sensor")
        device_id = "sensor1"  # Adjust if dynamic

        payload["timestamp"] = datetime.utcnow()

        # Fetch sensor state from `sensor_control` collection
        sensor_control = db["sensor_control"].find_one({"sensor_id": sensor_id})

        if not sensor_control:
            print(f"⚠️ Sensor {sensor_id} not found in sensor_control!")
            return

        active_sensors = {s: v["status"] for s, v in sensor_control["sensors"].items()}

        # Fetch thresholds from `thresholds` collection
        thresholds_data = get_thresholds(sensor_id)

        if thresholds_data:
            TEMP_THRESHOLD = float(thresholds_data.get("dht22", {}).get("temperature", 36))
            HUMIDITY_THRESHOLD = float(thresholds_data.get("dht22", {}).get("humidity", 80))
            GAS_THRESHOLD = float(thresholds_data.get("mq135", {}).get("gas", 2000))
        else:
            print(f"⚠️ Thresholds not found for {device_id}, using default values.")
            TEMP_THRESHOLD = 36
            GAS_THRESHOLD = 2000
            HUMIDITY_THRESHOLD = 80

        # Ignore sensors that are OFF
        # If sensor is OFF, set value to 0 instead of ignoring
        if "dht22" in active_sensors and active_sensors["dht22"] == "OFF":
            payload["temperature"] = 0
            payload["humidity"] = 0
        if "mq135" in active_sensors and active_sensors["mq135"] == "OFF":
            payload["airQuality"] = 0
        if "bmp280" in active_sensors and active_sensors["bmp280"] == "OFF":
            payload["bmp_temperature"] = 0
            payload["pressure"] = 0
            payload["altitude"] = 0
        if "lm393" in active_sensors and active_sensors["lm393"] == "OFF":
            payload["light"] = "OFF"  # For categorical values, use "OFF"
        if "sw420" in active_sensors and active_sensors["sw420"] == "OFF":
            payload["vibration"] = "OFF"


        # Update last received timestamp
        last_received_time[sensor_id] = time.time()

        # Mark sensor as online
        sensor_status_collection.update_one(
            {"sensor_id": sensor_id},
            {"$set": {"status": "online", "last_seen": payload["timestamp"]}},
            upsert=True
        )

        # Insert sensor data into its dedicated collection
        sensor_collection = db[sensor_id]
        sensor_collection.insert_one(payload)

        print(f"✅ Data saved for {sensor_id}: {payload}")

        # Check for alert conditions only for active sensors
        alerts = []
        if "temperature" in payload and payload["temperature"] > TEMP_THRESHOLD:
            alerts.append(f"High Temperature: {payload['temperature']}°C (Threshold: {TEMP_THRESHOLD}°C)")
        if "gas" in payload and payload["gas"] > GAS_THRESHOLD:
            alerts.append(f"High Gas Level: {payload['gas']} PPM (Threshold: {GAS_THRESHOLD} PPM)")
        if "humidity" in payload and payload["humidity"] > HUMIDITY_THRESHOLD:
            alerts.append(f"High Humidity: {payload['humidity']}% (Threshold: {HUMIDITY_THRESHOLD}%)")
        if "vibration" in payload and payload["vibration"] == "Vibration Detected!":
            alerts.append("Vibration Detected")
        if "light" in payload and payload["light"] == "Bright":
            alerts.append("Light Detected")

        if alerts and should_send_alert(sensor_id, alerts):
            print("🚨 Alert triggered!")
            alert_message = "\n".join(alerts)

            # Log alert
            alert_log = {
                "timestamp": payload["timestamp"],
                "alerts": alerts
            }
            alerts_collection.update_one(
                {"sensor_id": sensor_id},
                {
                    "$push": {"logs": alert_log},
                    "$set": {
                        "last_alert_time": datetime.utcnow(),
                        "last_alert_type": alerts
                    }
                },
                upsert=True
            )

            # Find users allocated to this sensor
            users = users_collection.find({"device_id": sensor_id})

            for user in users:
                chat_id = user.get("chat_id")

                # Send Telegram Alert
                if chat_id:
                    send_telegram_alert(chat_id, sensor_id, alert_message)

    except Exception as e:
        print(f"Error processing message: {e}")


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

# Initialize MQTT Client
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, 60)

# Start checking offline sensors
check_offline_sensors()

# Start MQTT loop
client.loop_forever()
