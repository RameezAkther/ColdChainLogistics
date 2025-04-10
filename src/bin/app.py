from flask import Flask, request, jsonify
from pymongo import MongoClient
from datetime import datetime

app = Flask(__name__)

# MongoDB Connection
client = MongoClient("mongodb://localhost:27017/")  # Update with your DB URL if needed
db = client["coldchain_db"]  # Database Name
collection = db["sensor_data"]  # Collection Name

print(client)
print(db)

@app.route('/store_data', methods=['POST'])
def store_sensor_data():
    data = request.json  # Get JSON data from ESP32

    # Add timestamp
    data["timestamp"] = datetime.now()

    # Insert into MongoDB
    collection.insert_one(data)

    return jsonify({"message": "Data stored successfully"}), 201

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
