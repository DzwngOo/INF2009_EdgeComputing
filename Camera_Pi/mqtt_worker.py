from inference_worker import InferenceResult
import queue, threading

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
    connected = threading.Event()
    connected.set() # ensure threading event is running even though mqtt is not implemented

    while not stop_evt.is_set():
        try:
            msg: InferenceResult = publish_q.get(timeout=0.2)
            print(msg)
        except queue.Empty:
            continue
