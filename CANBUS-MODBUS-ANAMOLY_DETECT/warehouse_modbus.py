import paho.mqtt.client as mqtt
import json
import time
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
from pymodbus.datastore import ModbusSequentialDataBlock
from pymodbus.device import ModbusDeviceIdentification
from collections import defaultdict

# MQTT Credentials
MQTT_BROKER = "874c8249bd8b49bf822b11e8975874c6.s1.eu.hivemq.cloud"
MQTT_PORT = 8883    
MQTT_USER = "Morningstar"
MQTT_PASSWORD = "PassWord5$"
MQTT_TOPICS = ["coldchain/truck1/sensor1", "coldchain/truck1/sensor1/location"]

# Assign Unique Modbus Holding Register Addresses
MODBUS_REGISTERS = {
    "temperature": 0,       # Holding Register 40001
    "humidity": 1,          # Holding Register 40002
    "airQuality": 2,        # Holding Register 40003
    "light": 3,             # Holding Register 40004
    "vibration": 4,         # Holding Register 40005
    "bmp_temperature": 5,   # Holding Register 40006
    "pressure": 6,          # Holding Register 40007
    "altitude": 7,          # Holding Register 40008
    "heartbeat": 99,        # Special Register for system health (400100)
    # Location data registers
    "latitude_whole": 10,   # Holding Register 40011 (Integer part)
    "latitude_frac": 11,    # Holding Register 40012 (Fractional part * 10000)
    "longitude_whole": 12,  # Holding Register 40013 (Integer part)
    "longitude_frac": 13,   # Holding Register 40014 (Fractional part * 10000)
    "wifi_count": 14,       # Holding Register 40015 (Number of WiFi networks)
    "wifi_signal": 15       # Holding Register 40016 (Strongest signal strength)
}

# Assign Unique Modbus Coil Addresses (for actuators)
MODBUS_COILS = {
    "fan": 0,              # Coil 00001 (Fan ON/OFF)
    "alarm": 1,            # Coil 00002 (Alarm ON/OFF)
}

# Setup Modbus Server (Warehouse Simulation)
store = ModbusSlaveContext(
    di=ModbusSequentialDataBlock(0, [0] * 10),    # Discrete Inputs (Read-only)
    co=ModbusSequentialDataBlock(0, [0] * 10),    # Coils (Fan, Alarm control)
    hr=ModbusSequentialDataBlock(0, [0] * 100),   # Holding Registers (Sensor Data)
    ir=ModbusSequentialDataBlock(0, [0] * 100),   # Input Registers (Similar to Holding)
)
context = ModbusServerContext(slaves=store, single=True)

# Dictionary to store the latest location data
latest_location_data = defaultdict(dict)

def update_location_data(sensor_id):
    """Updates Modbus registers with location data"""
    location = latest_location_data.get(sensor_id, {})
    
    try:
        # Process latitude if available
        if "latitude" in location and location["latitude"] != "-":
            lat = float(location["latitude"])
            lat_whole = int(lat)
            lat_frac = int(abs(lat - lat_whole) * 10000)  # 4 decimal places
            store.setValues(3, MODBUS_REGISTERS["latitude_whole"], [lat_whole])
            store.setValues(3, MODBUS_REGISTERS["latitude_frac"], [lat_frac])
        
        # Process longitude if available
        if "longitude" in location and location["longitude"] != "-":
            lon = float(location["longitude"])
            lon_whole = int(lon)
            lon_frac = int(abs(lon - lon_whole) * 10000)  # 4 decimal places
            store.setValues(3, MODBUS_REGISTERS["longitude_whole"], [lon_whole])
            store.setValues(3, MODBUS_REGISTERS["longitude_frac"], [lon_frac])
        
        # Process WiFi networks
        if "wifiNetworks" in location:
            networks = location["wifiNetworks"]
            store.setValues(3, MODBUS_REGISTERS["wifi_count"], [len(networks)])
            
            # Store strongest signal strength
            if networks:
                strongest = max(networks, key=lambda x: x["signalStrength"])
                store.setValues(3, MODBUS_REGISTERS["wifi_signal"], [abs(strongest["signalStrength"])])
                
    except (ValueError, KeyError) as e:
        print(f"⚠️ Error processing location data: {e}")

def on_message(client, userdata, msg):
    """ Updates the Modbus Server with real sensor data from MQTT """
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
            
            # Immediately update Modbus with location data
            update_location_data(sensor_id)
            print(f"📍 Updated Location Data → Lat: {data.get('latitude')}, Lon: {data.get('longitude')}")
            
        else:
            # Extract and Scale Sensor Data (Values are for simulation purposes)
            sensor_data = {
                "temperature": float(data["temperature"]),  # Scale for Modbus (30.5°C → 305)
                "humidity": float(data["humidity"]),
                "airQuality": float(data["airQuality"]),
                "light": 1 if data["light"] == "Bright" else 0,  # 0 = Dark, 1 = Bright
                "vibration": 1 if data["vibration"] == "Vibration Detected" else 0,
                "bmp_temperature": float(float(data["bmp_temperature"]) * 10),
                "pressure": float(data["pressure"]),
                "altitude": float(float(data["altitude"]) * 10),
            }

            # Update Modbus Holding Registers with Sensor Data
            for sensor, value in sensor_data.items():
                store.setValues(3, MODBUS_REGISTERS[sensor], [value])

            # Update Heartbeat Register (for system health)
            heartbeat = int(time.time())  # Store timestamp as heartbeat
            store.setValues(3, MODBUS_REGISTERS["heartbeat"], [heartbeat])

            # Control Actuators Based on Sensor Values (Example)
            # Example: Turn ON/OFF Fan and Alarm based on thresholds
            if sensor_data["temperature"] > 30.0:  # 30.0°C
                store.setValues(1, MODBUS_COILS["fan"], [1])  # Turn ON Fan
            else:
                store.setValues(1, MODBUS_COILS["fan"], [0])  # Turn OFF Fan

            if sensor_data["airQuality"] > 1100:
                store.setValues(1, MODBUS_COILS["alarm"], [1])  # Turn ON Alarm
            else:
                store.setValues(1, MODBUS_COILS["alarm"], [0])  # Turn OFF Alarm

            # Also update location data with sensor data
            update_location_data(sensor_id)

            # Print Modbus Updates
            print(f"🛠 Updated Modbus: Temp={sensor_data['temperature']}°C, Humidity={sensor_data['humidity']}%, AirQuality={sensor_data['airQuality']}")
            print(f"🔄 Actuators → Fan: {store.getValues(1, MODBUS_COILS['fan'], count=1)[0]}, Alarm: {store.getValues(1, MODBUS_COILS['alarm'], count=1)[0]}")
        
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

# Device Identification (For Modbus Clients)
identity = ModbusDeviceIdentification()
identity.VendorName = "ColdChain Inc."
identity.ProductCode = "CC-2025"
identity.VendorUrl = "https://coldchain.com"
identity.ProductName = "Cold Chain Logistics Monitor"
identity.ModelName = "IoT-MB-001"
identity.MajorMinorRevision = "1.0"

# Start Modbus Server
print("Starting Modbus Server on 127.0.0.1:502...")
print("Modbus Registers Map:")
print("  Sensor Data: 40001-40008")
print("  Location Data: 40011-40016")
StartTcpServer(context, identity=identity, address=("127.0.0.1", 502))