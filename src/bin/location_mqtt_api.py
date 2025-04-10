import paho.mqtt.client as mqtt
import requests
import json

# MQTT Credentials (same as ESP32)
MQTT_BROKER = "874c8249bd8b49bf822b11e8975874c6.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USER = "Rameez"
MQTT_PASSWORD = "PassWord5$"
MQTT_TOPIC = "coldchain/truck1/sensor1"

# RapidAPI Configuration
RAPIDAPI_KEY = "d4f11cda99mshaf0c893d26831e1p1e08ecjsnf73b7a997619"
RAPIDAPI_HOST = "ip-geo-location10.p.rapidapi.com"

def get_location_from_ip(ip_address):
    url = "https://ip-geo-location10.p.rapidapi.com/ip"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST
    }
    params = {"ip": ip_address}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        data = response.json()
        
        if data.get("code") == 200:
            location = data["result"]
            print(f"📍 Location for {ip_address}:")
            print(f"🌎 Country: {location['country']}")
            print(f"🏙️ City: {location['city']}")
            print(f"📌 Coordinates: {location['latitude']}, {location['longitude']}")
        else:
            print("❌ RapidAPI Error:", data.get("msg", "Unknown error"))
    except Exception as e:
        print("❌ RapidAPI Request Failed:", e)

def on_connect(client, userdata, flags, rc):
    print("✅ Connected to MQTT Broker")
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        print("\n📶 Received MQTT Data:")
        print(json.dumps(payload, indent=2))
        
        if "ip" in payload:
            get_location_from_ip(payload["ip"])
        else:
            print("⚠️ No IP address in payload")
    except Exception as e:
        print("❌ Error processing message:", e)

client = mqtt.Client()
client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
client.tls_set()  # Enable SSL

client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_forever()