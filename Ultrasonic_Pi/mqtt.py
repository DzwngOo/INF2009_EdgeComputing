import json, threading, sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import Camera_Pi.config as config  # Now you can import from Camera_Pi
import paho.mqtt.client as mqtt

# MQTT Callback function
def on_connect(client, userdata, flags, rc):
    print(f"Connected with result code {rc}")
    client.subscribe(config.TOPIC)  # Subscribe to your topic

def on_message(client, userdata, msg):
    print(f"Received message: {msg.payload.decode()} on topic {msg.topic}")
    
    # Try to parse the received message
    try:
        data = json.loads(msg.payload.decode())
        print(f"Received JSON data: {data}")
    except json.JSONDecodeError:
        print("Failed to decode JSON from message.")

class MqttSubscriberThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.client = mqtt.Client()
        self.client.on_connect = on_connect
        self.client.on_message = on_message

    def run(self):
        # Connect to the MQTT broker
        self.client.connect(config.BROKER_HOST, config.BROKER_PORT, 60)
        self.client.loop_forever()  # Start the loop to process incoming messages
