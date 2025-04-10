from flask import Flask, render_template, request, redirect, url_for, flash, session, g, jsonify
from flask_pymongo import PyMongo
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from bson import ObjectId
from datetime import timedelta, datetime
from src.visual_plots import generate_all_plots
import requests
from flask import current_app
import hashlib
import ipinfo

app = Flask(__name__)
app.config["MONGO_URI"] = "mongodb://localhost:27017/ColdChainDB"
app.config["SECRET_KEY"] = "supersecretkey"
app.config["SESSION_PROTECTION"] = "strong"
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=1)  # Keep session for 1 day
app.config["SESSION_PERMANENT"] = True
app.config["IPINFO_TOKEN"] = "56cea39573b0f6"
app.config["GOOGLE_GEOLOCATION_API_KEY"] = "AIzaSyBFTsCD_BxsMnowGCBGQv95QAk0UfP1doM"


# ipinfo_token = current_app.config.get("56cea39573b0f6")  # Add this to your config
# ipinfo_handler = ipinfo.getHandler(ipinfo_token)

last_wifi_hash = {}

TOKEN = "7801773734:AAG69gRWh9mqKZxJmmF8aIFycD-bKig2Gpo"

mongo = PyMongo(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

sensor_control_collection = mongo.db.sensor_control
threshold_collection = mongo.db.sensor_thresholds

TIME_WINDOW = timedelta(minutes=10)

def hash_wifi_data(wifi_list):
    """Create a hash from sorted MAC addresses + signal strength to detect changes."""
    wifi_data_str = ''.join(sorted(f"{ap['macAddress']}{ap['signalStrength']}" for ap in wifi_list))
    return hashlib.md5(wifi_data_str.encode()).hexdigest()

@app.before_request
def before_request():
    g.user = current_user

class User(UserMixin):
    def __init__(self, user_id, email, role):
        self.id = user_id
        self.email = email
        self.role = role

    @staticmethod
    def get(user_id):
        try:
            user = mongo.db.users.find_one({"_id": ObjectId(user_id)})  # Convert to ObjectId
            if user:
                return User(str(user["_id"]), user["email"], user.get("role", "User"))  # Default role
            return None
        except:
            return None

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

@app.route("/")
def home():
    print("Current User:", current_user.is_authenticated, "Role:", current_user.role if current_user.is_authenticated else "N/A")
    return render_template("index.html")

# Registration route
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        password = bcrypt.generate_password_hash(request.form["password"]).decode("utf-8")
        username = request.form["name"]
        phone_number = request.form["phone_number"]

        if mongo.db.users.find_one({"email": email}):
            flash("Email already exists!", "danger")
            return redirect(url_for("register"))

        mongo.db.users.insert_one({
            "username": username,
            "email": email,
            "password": password,
            "role": None,  # Assigned manually in MongoDB
            "device_allocated": False,
            "device_id":None,
            "phone_number": phone_number
        })

        flash("Registration successful! Wait for Admin approval.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": chat_id, "text": text})

@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    data = request.json

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"].strip()
        print(text)
        if text == "/start":
            # Send bot info message
            send_message(chat_id, "🤖 Welcome! Send your phone number to link with alerts.")
        
        elif text.isdigit() and len(text) >= 10:  # Check if it's a valid phone number
            # Register the phone number with chat ID
            user = mongo.db.users.find_one({"phone_number": text})
            if user:
                mongo.db.users.update_one(
                    {"phone_number": text},
                    {"$set": {"chat_id": chat_id}}
                )
                send_message(chat_id, "✅ Your Telegram is now linked to alerts!")
            else:
                send_message(chat_id, "❌ Phone number not found in our system. Contact admin.")

        else:
            send_message(chat_id, "⚠️ Invalid input.")

    return "OK"

# Login route
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = mongo.db.users.find_one({"email": email})
        if user and bcrypt.check_password_hash(user["password"], password):
            if not user["role"]:
                flash("Account not approved. Contact Admin.", "warning")
                return redirect(url_for("login"))

            user_obj = User(str(user["_id"]), user["email"], user["role"])
            login_user(user_obj)

            print("User logged in:", user_obj.id, "Role:", user_obj.role)  # Debugging
            flash("Login successful!", "success")
            return redirect(url_for("home"))

        flash("Invalid email or password!", "danger")

    return render_template("login.html")

@app.route("/iot_devices")
@login_required
def iot_devices():
    user = g.user  # Fetch logged-in user from Flask-Login

    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("logout"))

    role = user.role  # Get user role
    
    if role in ["Admin", "Operator"]:
        # Admin & Operator: Fetch all devices
        devices = list(mongo.db.sensor_status.find({}))
    else:
        # Warehouse User & Truck User: Fetch only the allocated device
        user_data = mongo.db.users.find_one({"_id": ObjectId(user.id)})  # Fetch full user data
        if user_data and user_data.get("device_allocated"):
            devices = list(mongo.db.sensor_status.find({"sensor_id": user_data["device_id"]}))
        else:
            devices = []

    return render_template("iot_devices.html", devices=devices)

@app.route("/get_iot_status")
def get_iot_status():
    devices = list(mongo.db.sensor_status.find({}, {"_id": 0}))  # Exclude _id
    return jsonify(devices)

@app.route("/device/<device_id>")
@login_required
def device_data(device_id): 
    """Fetch paginated sensor readings"""
    try:
        page = int(request.args.get("page", 1))
        per_page = 20  # 20 records per page
        skip_count = (page - 1) * per_page

        # Get total count of documents
        total_readings = mongo.db[device_id].count_documents({})
        total_pages = max(1, (total_readings + per_page - 1) // per_page)  # Ceiling division

        # Get paginated data
        readings = list(mongo.db[device_id].find(
            {},
            {"_id": 0, "sensor_id": 0}  # Exclude these fields
        ).sort("timestamp", -1).skip(skip_count).limit(per_page))

        # Convert timestamp to readable format
        for reading in readings:
            if "timestamp" in reading and isinstance(reading["timestamp"], datetime):
                reading["timestamp"] = reading["timestamp"].strftime("%Y-%m-%d %H:%M:%S")

        # Fetch sensor control status and thresholds (unchanged)
        sensor_control = sensor_control_collection.find_one({"sensor_id": device_id}, {"_id": 0, "sensors": 1})
        sensor_status = sensor_control.get("sensors", {}) if sensor_control else {}

        sensor_thresholds = threshold_collection.find_one({"sensor_id": device_id}, {"_id": 0, "thresholds": 1})
        thresholds = sensor_thresholds.get("thresholds", {}) if sensor_thresholds else {}

        return render_template(
            "device_data.html",
            device_id=device_id,
            readings=readings,
            total_pages=total_pages,
            current_page=page,
            sensor_status=sensor_status,
            thresholds=thresholds
        )

    except Exception as e:
        return str(e), 500

@app.route("/device/<device_id>/all_readings")
@login_required
def get_all_readings(device_id):
    """Fetch all readings for client-side processing"""
    try:
        readings = list(mongo.db[device_id].find(
            {},
            {"_id": 0, "sensor_id": 0}  # Exclude these fields
        ).sort("timestamp", -1))

        # Convert timestamp to readable format
        for reading in readings:
            if "timestamp" in reading and isinstance(reading["timestamp"], datetime):
                reading["timestamp"] = reading["timestamp"].isoformat()

        return jsonify({
            "readings": readings,
            "count": len(readings)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/live_data/<device_id>")
@login_required
def live_data(device_id):
    """Fetch latest sensor readings as JSON for real-time updates."""
    device_collection = mongo.db[device_id]

    # Get current time
    current_time = datetime.utcnow()

    # Fetch last 20 readings OR past 10 minutes of data
    readings = list(device_collection.find({
        "timestamp": {"$gte": current_time - TIME_WINDOW}
    }).sort("timestamp", -1).limit(20))  # Fetch latest 20 records

    # If no recent data, fetch the last available 20 records
    if not readings:
        readings = list(device_collection.find().sort("timestamp", -1).limit(20))

    # Extract sensor data
    timestamps = [r["timestamp"].strftime('%Y-%m-%d %H:%M:%S') for r in readings]
    temperatures = [r["temperature"] for r in readings]
    humidity = [r["humidity"] for r in readings]
    air_quality = [r["airQuality"] for r in readings]
    pressure = [r["pressure"] for r in readings]
    altitude = [r["altitude"] for r in readings]
    light = [1 if r["light"] == "Bright" else 0 for r in readings]
    vibration = [1 if r["vibration"] == "Vibration Detected" else 0 for r in readings]

    return jsonify({
        "timestamps": timestamps,
        "temperatures": temperatures,
        "humidity": humidity,
        "air_quality": air_quality,
        "pressure": pressure,
        "altitude": altitude,
        "light": light,
        "vibration": vibration
    })

@app.route("/location_data/<sensor_id>")
@login_required
def get_location(sensor_id):
    collection = mongo.db[f"{sensor_id}_location"]
    latest = collection.find_one(sort=[("timestamp", -1)])

    if not latest:
        return jsonify({"lat": None, "lng": None, "source": "none"})

    # Use GPS if valid
    if latest.get("gps_lat", 0) != 0 and latest.get("gps_lng", 0) != 0:
        return jsonify({"lat": latest["gps_lat"], "lng": latest["gps_lng"], "source": "gps"})

    # Use WiFi Geolocation
    wifi_data = latest.get("wifiNetworks", [])
    if not wifi_data:
        return get_ip_location_fallback()

    wifi_hash = hash_wifi_data(wifi_data)
    cached_hash = last_wifi_hash.get(sensor_id)

    if wifi_hash == cached_hash:
        if "location_cache" in latest:
            return jsonify({**latest["location_cache"], "source": "cache"})

    api_key = current_app.config.get("GOOGLE_GEOLOCATION_API_KEY")
    url = f"https://www.googleapis.com/geolocation/v1/geolocate?key={api_key}"
    payload = {
        "wifiAccessPoints": [
            {"macAddress": ap["macAddress"], "signalStrength": ap["signalStrength"]}
            for ap in wifi_data
        ]
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
        lat = result["location"]["lat"]
        lng = result["location"]["lng"]

        last_wifi_hash[sensor_id] = wifi_hash
        collection.update_one({"_id": latest["_id"]}, {"$set": {
            "location_cache": {"lat": lat, "lng": lng}
        }})

        return jsonify({"lat": lat, "lng": lng, "source": "wifi_api"})
    except Exception as e:
        print("Geolocation error:", e)
        return get_ip_location_fallback()

def get_ip_location_fallback():
    try:
        ipinfo_token = current_app.config.get("IPINFO_TOKEN")
        print("Using IPInfo token:", ipinfo_token)

        ipinfo_handler = ipinfo.getHandler(ipinfo_token)

        ip_address = request.headers.get("X-Forwarded-For", request.remote_addr)
        print("Client IP address:", ip_address)

        details = ipinfo_handler.getDetails(ip_address)
        print("IPInfo details.all:", details.all)

        loc = details.all.get("loc")
        print("Extracted 'loc':", loc)

        if loc:
            lat, lng = map(float, loc.split(","))
            print("Parsed lat/lng:", lat, lng)
            return jsonify({"lat": lat, "lng": lng, "source": "ip"})
        else:
            print("No location found in IPInfo details.")
            return jsonify({"lat": 12.9484, "lng": 80.1397, "source": "ip"})
    except Exception as e:
        print("IP Geolocation error:", e)
        return jsonify({"lat": None, "lng": None, "source": "ip_error"})

@app.route("/toggle_sensor/<device_id>", methods=["POST"])
def toggle_sensor(device_id):
    data = request.json
    sensor_id = data.get("sensor_id")
    status = data.get("status")

    if not sensor_id or status not in ["ON", "OFF"]:
        return jsonify({"error": "Invalid data"}), 400

    # Update sensor status inside a single document for the device
    sensor_control_collection.update_one(
        {"sensor_id": device_id},
        {"$set": {f"sensors.{sensor_id}.status": status}},
        upsert=True
    )

    return jsonify({"message": f"{sensor_id} turned {status}"}), 200

# Update Sensor Thresholds
@app.route("/update_thresholds/<device_id>", methods=["POST"])
def update_thresholds(device_id):
    data = request.json

    # Update thresholds inside a single document for the device
    threshold_collection.update_one(
        {"sensor_id": device_id},
        {"$set": {"thresholds": data}},
        upsert=True
    )

    return jsonify({"message": "Thresholds updated"}), 200

@app.route("/get_users")
def get_users():
    user_type = request.args.get("user_type")
    device_id = request.args.get("device_id")
    allocated_users = mongo.db.users.find({"device_allocated": False, "role": user_type})
    return jsonify([{ "_id": str(user["_id"]), "name": user["username"] } for user in allocated_users])

@app.route("/get_allocated_users")
def get_allocated_users():
    device_id = request.args.get("device_id")
    allocated_users = list(mongo.db.users.find({"device_id": device_id}))
    return jsonify(allocated_users)

@app.route("/allocate_sensor", methods=["POST"])
def allocate_sensor():
    data = request.json
    device_id = data["device_id"]
    user_id = data["user_id"]

    # Find the user
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})  

    if not user:
        return jsonify({"message": "User not found!"}), 400

    if user["device_allocated"]:
        return jsonify({"message": "This user already has an allocated sensor!"}), 400

    # Update user document
    mongo.db.users.update_one(
        {"_id": ObjectId(user_id)}, 
        {"$set": {"device_allocated": True, "device_id": device_id}}
    )

    return jsonify({"message": "Sensor allocated successfully!"})

@app.route("/deallocate_sensor", methods=["POST"])
def deallocate_sensor():
    data = request.json
    device_id = data["device_id"]
    user_id = data["user_id"]

    # Find the user with the given device_id and user_id
    user = mongo.db.users.find_one({"device_id": device_id, "_id": ObjectId(user_id)})

    if not user:
        return jsonify({"message": "User not found or not assigned to this sensor!"}), 400

    # Update the user document to remove the allocation
    mongo.db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"device_allocated": False, "device_id": None}}
    )

    return jsonify({"message": "User deallocated successfully!"})

@app.route("/alerts/<device_id>")
def get_alerts(device_id):
    """Fetch paginated alert logs from MongoDB with 20 records per page"""
    try:
        page = int(request.args.get("page", 1))
        per_page = 20  # Fixed 20 records per page
        skip_count = (page - 1) * per_page

        # Use aggregation to properly handle nested logs and pagination
        pipeline = [
            {"$match": {"sensor_id": device_id}},
            {"$unwind": "$logs"},
            {"$sort": {"logs.timestamp": -1}},  # Newest first
            {"$group": {
                "_id": None,
                "total_logs": {"$sum": 1},
                "logs": {"$push": "$logs"}
            }},
            {"$project": {
                "total_logs": 1,
                "paginated_logs": {
                    "$slice": ["$logs", skip_count, per_page]
                }
            }}
        ]

        result = list(mongo.db.alerts_collection.aggregate(pipeline))
        
        if not result:
            return jsonify({
                "alerts": [],
                "total_pages": 1,
                "current_page": page,
                "total_logs": 0
            })

        total_logs = result[0]['total_logs']
        total_pages = max(1, (total_logs + per_page - 1) // per_page)  # Ceiling division

        # Format the alerts
        formatted_alerts = [{
            "timestamp": log["timestamp"].isoformat() if isinstance(log["timestamp"], datetime) else log["timestamp"],
            "sensor_id": device_id,
            "alerts": ", ".join(log["alerts"])
        } for log in result[0]['paginated_logs']]

        return jsonify({
            "alerts": formatted_alerts,
            "total_pages": total_pages,
            "current_page": page,
            "total_logs": total_logs
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Admin Dashboard Route
@app.route("/admin_dashboard")
@login_required
def admin_dashboard():
    if current_user.role != "Admin":
        flash("Access Denied!", "danger")
        return redirect(url_for("home"))

    users = mongo.db.users.find()  # Fetch all users
    return render_template("admin_dashboard.html", users=users)

@app.route("/approve_user/<user_id>", methods=["POST"])
@login_required
def approve_user(user_id):
    if current_user.role != "Admin":
        return jsonify({"success": False, "message": "Access Denied!"})

    data = request.get_json()
    selected_role = data.get("role")

    if selected_role not in ["Admin", "Operator", "Truck User", "Warehouse User"]:
        return jsonify({"success": False, "message": "Invalid role selection!"})

    mongo.db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"role": selected_role}})

    # Define badge classes dynamically
    badge_classes = {
        "Admin": "bg-danger",
        "Operator": "bg-warning",
        "Truck User": "bg-primary",
        "Warehouse User": "bg-info"
    }

    return jsonify({"success": True, "role": selected_role, "badge_class": badge_classes[selected_role]})

# Delete User Route
@app.route("/delete_user/<user_id>")
@login_required
def delete_user(user_id):
    if current_user.role != "Admin":
        flash("Access Denied!", "danger")
        return redirect(url_for("home"))

    mongo.db.users.delete_one({"_id": ObjectId(user_id)})
    flash("User deleted successfully!", "danger")
    return redirect(url_for("admin_dashboard"))

# Logout route
@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully!", "info")
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(debug=True)
