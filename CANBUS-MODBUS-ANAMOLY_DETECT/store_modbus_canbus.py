import paho.mqtt.client as mqtt
import json
from pymongo import MongoClient
from collections import defaultdict

# MongoDB Setup
mongo_client = MongoClient("mongodb://localhost:27017/")
db = mongo_client["ColdChainDB"]
collection = db["modbus_canbus_sensor_data"]

# MQTT Credentials
MQTT_BROKER = "874c8249bd8b49bf822b11e8975874c6.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USER = "Morningstar"
MQTT_PASSWORD = "PassWord5$"
MQTT_TOPICS = ["coldchain/truck1/sensor1", "coldchain/truck1/sensor1/location"]

# Dictionary to store the latest location data for each sensor
latest_location_data = defaultdict(dict)

def on_message(client, userdata, msg):
    """ Stores MQTT Data into MongoDB with Modbus & CAN Bus ready format """
    try:
        topic = msg.topic
        data = json.loads(msg.payload.decode())
        sensor_id = data["sensor_id"]
        
        if topic.endswith("location"):
            # Store location data
            latest_location_data[sensor_id] = {
                "latitude": data.get("latitude", "-"),
                "longitude": data.get("longitude", "-"),
                "wifiNetworks": data.get("wifiNetworks", [])
            }
        else:
            # Get the latest location data for this sensor
            location = latest_location_data.get(sensor_id, {
                "latitude": "-",
                "longitude": "-",
                "wifiNetworks": []
            })
            
            formatted_data = {
                "modbus": {  # Warehouse Ready Format
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
                "canbus": {  # Truck Ready Format
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
                "original": data,
                "location_data": location
            }

            collection.insert_one(formatted_data)
            print(f"Stored in MongoDB: {formatted_data}")

    except Exception as e:
        print(f"Error processing MQTT message: {e}")

# MQTT Setup
client = mqtt.Client()
client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
client.tls_set()  
client.on_message = on_message
client.connect(MQTT_BROKER, MQTT_PORT, 60)

# Subscribe to multiple topics
for topic in MQTT_TOPICS:
    client.subscribe(topic)

client.loop_forever()