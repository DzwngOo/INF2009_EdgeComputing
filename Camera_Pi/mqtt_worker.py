import queue, threading
import time
import paho.mqtt.client as mqtt
from typing import Any

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
    connected = threading.Event()

    def on_connect(_client, _userdata, _flags, rc):
        if rc == 0:
            connected.set()
            print(f"[MQTT][CAMERA] Connected to broker {broker_host}:{broker_port}")
        else:
            print(f"[MQTT][CAMERA] Connect failed with rc={rc}")

    def on_disconnect(_client, _userdata, rc):
        connected.clear()
        if rc == 0:
            print("[MQTT][CAMERA] Disconnected cleanly.")
        else:
            print(f"[MQTT][CAMERA] Connection lost (rc={rc}). Reconnecting…")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    client.loop_start()

    # Keep trying initial connect so Camera Pi reflects broker/link recovery in logs.
    while not stop_evt.is_set() and not connected.is_set():
        try:
            print(f"[MQTT][CAMERA] Connecting to broker {broker_host}:{broker_port}…")
            client.connect(broker_host, broker_port, 60)
            time.sleep(1)
        except Exception as e:
            print(f"[MQTT][CAMERA] Connect attempt failed: {e}")
            time.sleep(2)

    while not stop_evt.is_set():
        try:
            msg: Any = publish_q.get(timeout=0.2)
            print(f"Sending message: {msg}")
            
            # Convert the message to a string (or any format you prefer)
            payload = msg.to_json()  # Assuming you want to send the message as a JSON string
            
            # Publish the message to the broker
            info = client.publish(topic, payload, qos=qos, retain=retain)
            if getattr(info, "rc", mqtt.MQTT_ERR_NO_CONN) != mqtt.MQTT_ERR_SUCCESS:
                print(f"[MQTT][CAMERA] Publish not sent yet (rc={info.rc}). Waiting for reconnect.")
            cam_publish_done_ns = time.time_ns()
            cam_publish_done_perf_ns = time.perf_counter_ns()
            print(
                f"[E2E_LOG][CAMERA] msg_id={msg.msg_id} "
                f"cam_capture_start_ns={msg.cam_capture_start_ns} "
                f"cam_capture_start_perf_ns={msg.cam_capture_start_perf_ns} "
                f"cam_mqtt_publish_done_ns={cam_publish_done_ns} "
                f"cam_mqtt_publish_done_perf_ns={cam_publish_done_perf_ns} "
                f"mid={getattr(info, 'mid', -1)}"
            )
        except queue.Empty:
            continue

    # Stop the loop once the event is set
    client.loop_stop()
    try:
        client.disconnect()
    except Exception:
        pass
