import paho.mqtt.client as mqtt
import json
from pymongo import MongoClient
from collections import defaultdict, deque
import numpy as np
import ssl
import time
import requests

# === MongoDB Setup ===
mongo_client = MongoClient("mongodb://localhost:27017/")
db = mongo_client["ColdChainDB"]
collection_anomalies = db["sensor_data_with_anomalies"]

# === MQTT Setup ===
MQTT_BROKER = "874c8249bd8b49bf822b11e8975874c6.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USER = "Morningstar"
MQTT_PASSWORD = "PassWord5$"
MQTT_TOPICS = ["coldchain/truck1/sensor1", "coldchain/truck1/sensor1/location"]

# === Sensor State ===
ROLLING_WINDOW = 30
sensor_stats = defaultdict(lambda: defaultdict(lambda: deque(maxlen=ROLLING_WINDOW)))
latest_location_data = defaultdict(dict)

# === Thresholds & Categorical Definitions ===
Z_THRESHOLDS = {
    "early": 2,          # Soft anomaly — slightly outside expected behavior
    "current": 3.5,        # Medium anomaly — more significant deviation
    "post": 4          # Strong anomaly — action might be required
}

CATEGORICAL_FIELDS = {
    "vibration": ["No Vibration", "Vibration Detected"],
    "light": ["Dark", "Bright"]
}
NUMERICAL_FIELDS = [
    "temperature", "humidity", "airQuality", "bmp_temperature",
    "pressure", "altitude"
]

# === Telegram Config (Optional) ===
TELEGRAM_ENABLED = False
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

def send_telegram_alert(message):
    if TELEGRAM_ENABLED:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
            response = requests.post(url, data=data)
            if response.status_code == 200:
                print(f"[Telegram] Alert sent.")
            else:
                print(f"[Telegram] Failed: {response.text}")
        except Exception as e:
            print(f"[Telegram] Error: {e}")

def detect_numerical_anomaly(sensor_id, metric, value):
    values = sensor_stats[sensor_id][metric]
    values.append(value)
    if len(values) < 10:
        return None
    mean = np.mean(values)
    std = np.std(values)
    if std == 0:
        return None
    z_score = abs((value - mean) / std)
    if z_score > Z_THRESHOLDS["post"]:
        return "post_warning"
    elif z_score > Z_THRESHOLDS["current"]:
        return "current_warning"
    elif z_score > Z_THRESHOLDS["early"]:
        return "early_warning"
    return None

def detect_categorical_anomaly(field, value):
    expected_values = CATEGORICAL_FIELDS.get(field, [])
    if value not in expected_values:
        return "unexpected_category"
    return None

def on_message(client, userdata, msg):
    try:
        topic = msg.topic
        data = json.loads(msg.payload.decode())
        sensor_id = data["sensor_id"]

        if topic.endswith("location"):
            latest_location_data[sensor_id] = {
                "latitude": data.get("latitude", "-"),
                "longitude": data.get("longitude", "-"),
                "wifiNetworks": data.get("wifiNetworks", [])
            }
            return

        location = latest_location_data.get(sensor_id, {
            "latitude": "-", "longitude": "-", "wifiNetworks": []
        })

        anomalies = {}

        # Numerical
        for metric in NUMERICAL_FIELDS:
            try:
                value = float(data.get(metric))
                warning = detect_numerical_anomaly(sensor_id, metric, value)
                if warning:
                    anomalies[metric] = {
                        "value": value,
                        "warning": warning,
                        "timestamp": time.time()
                    }
                    print(f"[ANOMALY] {sensor_id} - {metric}: {value} ({warning})")
            except Exception:
                continue

        # Categorical
        for field in CATEGORICAL_FIELDS:
            value = data.get(field)
            if value is not None:
                warning = detect_categorical_anomaly(field, value)
                if warning:
                    anomalies[field] = {
                        "value": value,
                        "warning": warning,
                        "timestamp": time.time()
                    }
                    print(f"[ANOMALY] {sensor_id} - {field}: '{value}' ({warning})")

        formatted_data = {
            "sensor_id": sensor_id,
            "timestamp": time.time(),
            "modbus": {
                "temperature": data["temperature"],
                "humidity": data["humidity"],
                "airQuality": data["airQuality"],
                "light": data["light"],
                "vibration": data["vibration"],
                "bmp_temperature": data["bmp_temperature"],
                "pressure": data["pressure"],
                "altitude": data["altitude"],
                "location": {
                    "latitude": location["latitude"],
                    "longitude": location["longitude"]
                }
            },
            "canbus": {
                "temperature": data["temperature"],
                "humidity": data["humidity"],
                "airQuality": data["airQuality"],
                "light": data["light"],
                "vibration": data["vibration"],
                "bmp_temperature": data["bmp_temperature"],
                "pressure": data["pressure"],
                "altitude": data["altitude"],
                "gps": {
                    "lat": location["latitude"],
                    "lon": location["longitude"],
                    "wifiNetworks": location["wifiNetworks"]
                }
            },
            "anomalies": anomalies,
            "raw": data
        }

        collection_anomalies.insert_one(formatted_data)
        print(f"[DB] Stored: {sensor_id} | Anomalies: {len(anomalies)}")

        if any(val["warning"] == "post_warning" for val in anomalies.values()):
            message = f"[🚨 ALERT] Severe anomaly on {sensor_id}\n" + \
                      "\n".join(f"{k}: {v['value']} ({v['warning']})" for k, v in anomalies.items())
            send_telegram_alert(message)

    except Exception as e:
        print(f"[ERROR] on_message: {e}")

# === MQTT Init ===
client = mqtt.Client()
client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
client.on_message = on_message
client.connect(MQTT_BROKER, MQTT_PORT, 60)

for topic in MQTT_TOPICS:
    client.subscribe(topic)
    print(f"[MQTT] Subscribed to: {topic}")

print("[System] 🚀 Edge Anomaly Detection Engine Started...\n")
client.loop_forever()
