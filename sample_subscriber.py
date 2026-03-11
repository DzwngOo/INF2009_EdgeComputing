# To move to the broker pi once setup
import paho.mqtt.client as mqtt
import Camera_Pi.config as config
import json

# MQTT Broker Settings
BROKER_HOST = config.BROKER_HOST
BROKER_PORT = config.BROKER_PORT
TOPIC = config.TOPIC

# Callback when the client connects to the broker
def on_connect(client, userdata, flags, rc):
    print(f"Connected with result code {rc}")
    # Subscribe to the topic after connecting
    client.subscribe(TOPIC)

# Callback when a message is received from the broker
def on_message(client, userdata, msg):
    print(f"Received message: {msg.payload.decode()} on topic {msg.topic}")

    # Parse the JSON payload
    try:
        data = json.loads(msg.payload.decode())
        
        # Extract individual values from the JSON data
        ts_ms = data.get("ts_ms")
        total_count = data.get("total_count")
        seated_count = data.get("seated_count")
        standing_count = data.get("standing_count")
        roi_counts = data.get("roi_counts")
        capacity = data.get("capacity")
        confidence_avg = data.get("confidence_avg")
        occupancy_ratio = data.get("occupancy_ratio")
        cabin_status = data.get("cabin_status")
        
        left_zone = roi_counts.get("left_zone") if roi_counts else None
        right_zone = roi_counts.get("right_zone") if roi_counts else None
        
        # Print the extracted values
        print(f"Timestamp (ms): {ts_ms}")
        print(f"Total count: {total_count}")
        print(f"Seated count: {seated_count}")
        print(f"Standing count: {standing_count}")
        print(f"Left zone count: {left_zone}")
        print(f"Right zone count: {right_zone}")
        print(f"Capacity: {capacity}")
        print(f"Average confidence: {confidence_avg}")
        print(f"Occupancy ratio: {occupancy_ratio}")
        print(f"Cabin status: {cabin_status}")
    
    except json.JSONDecodeError:
        print("Failed to decode JSON from message.")


# Create an MQTT client instance
client = mqtt.Client()

# Assign the callback functions
client.on_connect = on_connect
client.on_message = on_message

# Connect to the broker
client.connect(BROKER_HOST, BROKER_PORT, 60)

# Start the loop to process incoming messages
client.loop_forever()
