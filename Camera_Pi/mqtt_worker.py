from inference_worker import InferenceResult
import queue, threading
import paho.mqtt.client as mqtt

# ---------- mqtt publisher thread ----------
## Sample MQTT thread, whoever doing MQTT can just replace this ##
# I only kept the multithreading logic #
def mqtt_publisher_loop(
    publish_q: queue.Queue,
    stop_evt: threading.Event,
    broker_host: str,
    broker_port: int,
    topic: str,
    client_id: str = "camera_pi_pub",
    qos: int = 0,
    retain: bool = False,
):
     # MQTT client setup
    client = mqtt.Client(client_id)
    
    # Connect to the broker
    client.connect(broker_host, broker_port, 60)
    
    # Ensure connection happens
    client.loop_start()

    connected = threading.Event()
    connected.set() # ensure threading event is running even though mqtt is not implemented

    while not stop_evt.is_set():
        try:
            msg: InferenceResult = publish_q.get(timeout=0.2)
            print(f"Sending message: {msg}")
            
            # Convert the message to a string (or any format you prefer)
            payload = msg.to_json()  # Assuming you want to send the message as a JSON string
            
            # Publish the message to the broker
            client.publish(topic, payload, qos=qos, retain=retain)
        except queue.Empty:
            continue

    # Stop the loop once the event is set
    client.loop_stop()
