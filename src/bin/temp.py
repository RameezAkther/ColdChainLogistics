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
MQTT_BROKER = "192.168.1.3"
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

# Function to get sensor thresholds from MongoDB
def get_thresholds(sensor_id):
    thresholds_doc = sensor_thresholds_collection.find_one({"sensor_id": sensor_id})
    if thresholds_doc:
        return thresholds_doc.get("thresholds", {})
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
        payload["timestamp"] = datetime.utcnow()

        # Fetch sensor state from sensor_control collection
        sensor_control = sensor_control_collection.find_one({"sensor_id": sensor_id})
        if not sensor_control:
            print(f"⚠️ Sensor {sensor_id} not found in sensor_control!")
            return

        active_sensors = {s: v["status"] for s, v in sensor_control.get("sensors", {}).items()}

        # Fetch thresholds from sensor_thresholds collection
        thresholds_data = get_thresholds(sensor_id)

        # Default values if not found in DB
        TEMP_THRESHOLD = int(thresholds_data.get("dht22", {}).get("temperature", 36))
        HUMIDITY_THRESHOLD = int(thresholds_data.get("dht22", {}).get("humidity", 80))
        GAS_THRESHOLD = int(thresholds_data.get("mq135", {}).get("gas", 2000))

        # Ignore sensors that are OFF
        if "dht22" in active_sensors and active_sensors["dht22"] == "OFF":
            payload["temperature"] = 0
            payload["humidity"] = 0
        if "mq135" in active_sensors and active_sensors["mq135"] == "OFF":
            payload["airQuality"] = 0

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

        # Check for alert conditions
        alerts = []
        if "temperature" in payload and payload["temperature"] > TEMP_THRESHOLD:
            alerts.append(f"High Temperature: {payload['temperature']}°C (Threshold: {TEMP_THRESHOLD}°C)")
        if "gas" in payload and payload["gas"] > GAS_THRESHOLD:
            alerts.append(f"High Gas Level: {payload['gas']} PPM (Threshold: {GAS_THRESHOLD} PPM)")
        if "humidity" in payload and payload["humidity"] > HUMIDITY_THRESHOLD:
            alerts.append(f"High Humidity: {payload['humidity']}% (Threshold: {HUMIDITY_THRESHOLD}%)")

        if alerts:
            print("🚨 Alert triggered!")
            alert_message = "\n".join(alerts)

            # Log alert
            alert_log = {
                "timestamp": payload["timestamp"],
                "alerts": alerts
            }
            alerts_collection.update_one(
                {"sensor_id": sensor_id},
                {"$push": {"logs": alert_log}},
                upsert=True
            )
    
    except Exception as e:
        print(f"Error processing message: {e}")

# Check sensor status periodically
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

# Initialize MQTT Client
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message
client.connect(MQTT_BROKER, MQTT_PORT, 60)

# Start checking offline sensors
check_offline_sensors()

# Start MQTT loop
client.loop_forever()
