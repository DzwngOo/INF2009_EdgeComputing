import json, threading, sys, os
import queue
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import Camera_Pi.config as config  # Now you can import from Camera_Pi
import paho.mqtt.client as mqtt

class MqttSubscriberThread(threading.Thread):
    def __init__(self, mqtt_queue):
        threading.Thread.__init__(self)
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.mqtt_queue = mqtt_queue

    def run(self):
        # Connect to the MQTT broker
        self.client.connect(config.BROKER_HOST, config.BROKER_PORT, 60)
        self.client.loop_forever()  # Start the loop to process incoming messages

    # MQTT Callback function
    def on_connect(self, client, userdata, flags, rc):
        print(f"Connected with result code {rc}")
        client.subscribe(config.TOPIC)  # Subscribe to your topic

    def on_message(self, client, userdata, msg):
        # print(f"Received message: {msg.payload.decode()} on topic {msg.topic}")
        
        # Try to parse the received message
        try:
            data = json.loads(msg.payload.decode())
            # print(f"Received JSON data: {data}")
            while True:
                try:
                    self.mqtt_queue.put_nowait(data)
                    break
                except queue.Full:
                    try:
                        _ = self.mqtt_queue.get_nowait()
                    except queue.Empty:
                        break
        except json.JSONDecodeError:
            print("Failed to decode JSON from message.")
