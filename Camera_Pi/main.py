import time, config, threading, queue
from inference_worker import inference_loop, InferenceResult
from mqtt_worker import mqtt_publisher_loop

# ---------- shared state ----------
STOP = threading.Event()
PUBLISH_Q: queue.Queue[InferenceResult] = queue.Queue(maxsize=50)  # prevents RAM blow-up

# ---------- main ----------
def main():
    # MQTT Configs
    broker_host = config.BROKER_HOST
    broker_port = config.BROKER_PORT
    topic = config.TOPIC
    # Inference Configs
    max_fps = float(getattr(config, "MAX_FPS", 0.0))
    model_path = config.MODEL
    device = config.DEVICE
    source = config.SOURCE
    imgsz = config.IMGSZ
    conf = config.CONF

    t_infer = threading.Thread(
        target=inference_loop,
        name="InferenceThread",
        args=(PUBLISH_Q, STOP),
        kwargs={
        "fps": max_fps,
        "model_path": model_path,
        "device": device,
        "source": source,
        "imgsz": imgsz,
        "conf": conf,
        "debug_show": True # disable it on actual demo
    },
        daemon=True,
    )

    t_mqtt = threading.Thread(
        target=mqtt_publisher_loop,
        name="MQTTPublishThread",
        args=(PUBLISH_Q, STOP, broker_host, broker_port, topic),
        kwargs={"qos": 0, "retain": False},
        daemon=True,
    )

    t_infer.start()
    t_mqtt.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        STOP.set()
        t_infer.join(timeout=2)
        t_mqtt.join(timeout=2)


if __name__ == "__main__":
    main()
