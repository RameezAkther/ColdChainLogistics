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

# HiveMQ Cloud Credentials
MQTT_BROKER = "874c8249bd8b49bf822b11e8975874c6.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USER = "Rameez"
MQTT_PASSWORD = "PassWord5$"
MQTT_TOPIC = "coldchain/truck1/sensor1"

# Cooldown Period (in seconds)
ALERT_COOLDOWN = 60  # 1 minute

# Dictionary to track last received timestamps
last_received_time = {}

# Timeout interval to consider a sensor offline
TIMEOUT_INTERVAL = 10  # seconds
TELEGRAM_BOT_TOKEN = "7801773734:AAG69gRWh9mqKZxJmmF8aIFycD-bKig2Gpo"

# Function to fetch thresholds from MongoDB
def get_thresholds(sensor_id):
    thresholds_doc = sensor_thresholds_collection.find_one({"sensor_id": sensor_id})
    return thresholds_doc.get("thresholds", {}) if thresholds_doc else {}

# Function to send a Telegram alert
def send_telegram_alert(chat_id, sensor_id, alert_message):
    if chat_id:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {"chat_id": chat_id, "text": f"🚨 Alert from {sensor_id}:\n{alert_message}"}
            requests.post(url, json=data)
        except Exception as e:
            print(f"Error sending Telegram alert: {e}")

# Function to determine if an alert should be sent
def should_send_alert(sensor_id, new_alerts):
    last_alert = alerts_collection.find_one({"sensor_id": sensor_id}, {"last_alert_time": 1, "last_alert_type": 1})
    if last_alert:
        last_alert_time = last_alert.get("last_alert_time")
        last_alert_type = last_alert.get("last_alert_type", [])
        if last_alert_time and datetime.utcnow() - last_alert_time < timedelta(seconds=ALERT_COOLDOWN):
            if any(alert not in last_alert_type for alert in new_alerts):
                return True
            return False
    return True

# Function to get enabled sensors
def get_enabled_sensors(sensor_id):
    sensor_doc = sensor_control_collection.find_one({"sensor_id": sensor_id})
    return {k: v["status"] for k, v in sensor_doc.get("sensors", {}).items()} if sensor_doc else {}

# MQTT Callback - When connected
def on_connect(client, userdata, flags, rc):
    print("Connected to HiveMQ Broker")
    client.subscribe(MQTT_TOPIC)

# MQTT Callback - When a message is received
def on_message(client, userdata, msg):
    global last_received_time
    try:
        payload = json.loads(msg.payload.decode())
        sensor_id = payload.get("sensor_id", "unknown_sensor")
        payload["timestamp"] = datetime.utcnow()
        
        sensor_control = sensor_control_collection.find_one({"sensor_id": sensor_id})
        if not sensor_control:
            print(f"⚠️ Sensor {sensor_id} not found in sensor_control!")
            return

        active_sensors = {s: v["status"] for s, v in sensor_control["sensors"].items()}
        thresholds_data = get_thresholds(sensor_id)
        TEMP_THRESHOLD = float(thresholds_data.get("dht22", {}).get("temperature", 36))
        HUMIDITY_THRESHOLD = float(thresholds_data.get("dht22", {}).get("humidity", 80))
        GAS_THRESHOLD = float(thresholds_data.get("mq135", {}).get("gas", 2000))

        last_received_time[sensor_id] = time.time()
        sensor_status_collection.update_one(
            {"sensor_id": sensor_id},
            {"$set": {"status": "online", "last_seen": payload["timestamp"]}},
            upsert=True
        )
        
        sensor_collection = db[sensor_id]
        sensor_collection.insert_one(payload)
        print(f"✅ Data saved for {sensor_id}: {payload}")
        
        alerts = []
        if payload.get("temperature", 0) > TEMP_THRESHOLD:
            alerts.append(f"High Temperature: {payload['temperature']}°C")
        if payload.get("gas", 0) > GAS_THRESHOLD:
            alerts.append(f"High Gas Level: {payload['gas']} PPM")
        if payload.get("humidity", 0) > HUMIDITY_THRESHOLD:
            alerts.append(f"High Humidity: {payload['humidity']}%")

        if alerts and should_send_alert(sensor_id, alerts):
            alert_message = "\n".join(alerts)
            alerts_collection.update_one(
                {"sensor_id": sensor_id},
                {"$push": {"logs": {"timestamp": payload["timestamp"], "alerts": alerts}},
                 "$set": {"last_alert_time": datetime.utcnow(), "last_alert_type": alerts}},
                upsert=True
            )
            for user in users_collection.find({"device_id": sensor_id}):
                if chat_id := user.get("chat_id"):
                    send_telegram_alert(chat_id, sensor_id, alert_message)
    except Exception as e:
        print(f"Error processing message: {e}")

# Function to check for offline sensors
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
    Timer(TIMEOUT_INTERVAL, check_offline_sensors).start()

# Initialize MQTT Client with TLS for HiveMQ
client = mqtt.Client()
client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
client.tls_set()
client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, 60)

check_offline_sensors()
client.loop_forever()
