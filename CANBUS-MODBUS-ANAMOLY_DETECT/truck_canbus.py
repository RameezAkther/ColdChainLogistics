import paho.mqtt.client as mqtt
import json
import time
import can
import struct  # For proper byte encoding
from collections import defaultdict

# MQTT Credentials
MQTT_BROKER = "874c8249bd8b49bf822b11e8975874c6.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USER = "Morningstar"
MQTT_PASSWORD = "PassWord5$"
MQTT_TOPICS = ["coldchain/truck1/sensor1", "coldchain/truck1/sensor1/location"]

# Simulated CAN Bus Interface (No real hardware, just for demo)
class FakeCANBus:
    def send(self, msg):
        print(f"Simulated CAN Message Sent: ID={hex(msg.arbitration_id)} DLC={len(msg.data)} Data={msg.data.hex()}")

bus = FakeCANBus()
timestamp = 0  # Initial timestamp

# Assign Unique CAN IDs for Each Sensor Type (Industry Standard Practice)
CAN_IDS = {
    "temperature": 0x200,
    "humidity": 0x201,
    "airQuality": 0x202,
    "light": 0x203,
    "vibration": 0x204,
    "bmp_temperature": 0x205,
    "pressure": 0x206,
    "altitude": 0x207,
    "heartbeat": 0x1FF,  # Special ID for system health status
    "gps_latitude": 0x208,
    "gps_longitude": 0x209,
    "wifi_network": 0x20A  # For WiFi network data
}

# Dictionary to store the latest location data for each sensor
latest_location_data = defaultdict(dict)

def send_gps_data(sensor_id):
    """Helper function to send GPS data over CAN bus"""
    global timestamp
    location = latest_location_data.get(sensor_id, {})
    
    # Send latitude if available
    if "latitude" in location and location["latitude"] != "-":
        try:
            # Convert latitude to integer (multiply by 1e6 for precision)
            lat = int(float(location["latitude"]) * 1000000)
            lat_bytes = struct.pack(">i", lat)  # 4-byte signed integer
            timestamp += 1
            can_msg = can.Message(
                arbitration_id=CAN_IDS["gps_latitude"], 
                data=[timestamp & 0xFF] + list(lat_bytes)
            )
            bus.send(can_msg)
            print(f"📡 CAN GPS Latitude → ID: {hex(CAN_IDS['gps_latitude'])}, Value: {lat}")
        except ValueError:
            pass
    
    # Send longitude if available
    if "longitude" in location and location["longitude"] != "-":
        try:
            # Convert longitude to integer (multiply by 1e6 for precision)
            lon = int(float(location["longitude"]) * 1000000)
            lon_bytes = struct.pack(">i", lon)  # 4-byte signed integer
            timestamp += 1
            can_msg = can.Message(
                arbitration_id=CAN_IDS["gps_longitude"], 
                data=[timestamp & 0xFF] + list(lon_bytes)
            )
            bus.send(can_msg)
            print(f"📡 CAN GPS Longitude → ID: {hex(CAN_IDS['gps_longitude'])}, Value: {lon}")
        except ValueError:
            pass

def send_wifi_data(sensor_id):
    """Helper function to send WiFi network data over CAN bus"""
    global timestamp
    location = latest_location_data.get(sensor_id, {})
    
    if "wifiNetworks" in location:
        for network in location["wifiNetworks"]:
            try:
                # Convert MAC address to bytes (first 3 bytes only for CAN frame)
                mac_parts = network["macAddress"].split(':')
                mac_bytes = bytes.fromhex(''.join(mac_parts[:3]))  # First 3 bytes
                
                # Signal strength (1 byte)
                signal = max(-128, min(127, network["signalStrength"]))  # Clamp to signed byte
                
                # Construct message (3 bytes MAC + 1 byte signal strength)
                data = list(mac_bytes) + [signal & 0xFF]
                
                timestamp += 1
                can_msg = can.Message(
                    arbitration_id=CAN_IDS["wifi_network"],
                    data=[timestamp & 0xFF] + data
                )
                bus.send(can_msg)
                print(f"📡 CAN WiFi Network → ID: {hex(CAN_IDS['wifi_network'])}, MAC: {network['macAddress']}, Signal: {signal}dBm")
            except (ValueError, KeyError):
                continue

def on_message(client, userdata, msg):
    """ Converts MQTT Data into CAN Bus format & transmits sensor values sequentially """
    global timestamp  # Use global timestamp variable

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
            
            # Immediately send the new location data over CAN bus
            send_gps_data(sensor_id)
            send_wifi_data(sensor_id)
            
        else:
            # Extract sensor data with correct types
            sensor_data = {
                "temperature": float(data["temperature"]),
                "humidity": float(data["humidity"]),
                "airQuality": float(data["airQuality"]),
                "light": 1 if data["light"] == "Bright" else 0,  # Convert to numeric
                "vibration": 1 if data["vibration"] == "Vibration" else 0,
                "bmp_temperature": float(data["bmp_temperature"]),
                "pressure": float(data["pressure"]),
                "altitude": float(data["altitude"])
            }

            # Transmit Each Sensor Data One-by-One
            for sensor, value in sensor_data.items():
                timestamp += 1  # Increment timestamp for each message

                # Scale float values to fit in CAN frames (1 decimal precision)
                if isinstance(value, float):
                    value = int(value * 10)  

                # Ensure value fits into 2 bytes (CAN limit for small payloads)
                value_bytes = struct.pack(">h", value)  # Big-endian, signed 16-bit

                # Construct CAN message
                can_msg = can.Message(
                    arbitration_id=CAN_IDS[sensor], 
                    data=[timestamp & 0xFF] + list(value_bytes)
                )
                bus.send(can_msg)

                print(f"📡 CAN Bus Data → ID: {hex(CAN_IDS[sensor])}, Timestamp: {timestamp}, {sensor}: {value}")

                time.sleep(0.1)  # Smaller delay for faster transmission

            # Send the latest location data after sensor data
            send_gps_data(sensor_id)
            send_wifi_data(sensor_id)

            # Send Heartbeat Signal Every 10 Messages
            if timestamp % 10 == 0:
                heartbeat_msg = can.Message(
                    arbitration_id=CAN_IDS["heartbeat"], 
                    data=[timestamp & 0xFF, 0xAA]  # 0xAA = "System OK"
                )
                bus.send(heartbeat_msg)
                print(f"💓 CAN Heartbeat Sent → ID: {hex(CAN_IDS['heartbeat'])}, Timestamp: {timestamp}")

    except Exception as e:
        print(f"❌ Error processing MQTT message: {e}")

# MQTT Setup
client = mqtt.Client()
client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
client.tls_set()  # Enable SSL/TLS
client.on_message = on_message
client.connect(MQTT_BROKER, MQTT_PORT, 60)

# Subscribe to multiple topics
for topic in MQTT_TOPICS:
    client.subscribe(topic)

client.loop_start()

# Keep Running
while True:
    time.sleep(1)