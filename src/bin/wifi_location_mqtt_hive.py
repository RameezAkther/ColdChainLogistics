import paho.mqtt.client as mqtt
import ssl
import json

MQTT_BROKER = "874c8249bd8b49bf822b11e8975874c6.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USER = "Rameez"
MQTT_PASSWORD = "PassWord5$"
MQTT_TOPIC = "coldchain/truck1/sensor1"

def on_connect(client, userdata, flags, rc):
    print("✅ Connected to HiveMQ")
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        print(f"\n📶 WiFi Data from {payload['sensor_id']}:")
        for ap in payload["wifiAccessPoints"]:
            print(f"  - MAC: {ap['macAddress']}, Signal: {ap['signalStrength']} dBm")
    except Exception as e:
        print(f"Error processing message: {e}")

client = mqtt.Client()
client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
client.tls_set(tls_version=ssl.PROTOCOL_TLS)

client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_forever()
