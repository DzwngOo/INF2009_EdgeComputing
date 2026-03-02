import time, json, queue, config, threading, cv2
from dataclasses import dataclass
from ultralytics import YOLO

# ---------- data model ----------
@dataclass
class InferenceResult:
    ts_ms: int
    person_count: int
    capacity: int
    confidence_avg: float

    def to_json(self) -> str:
        return json.dumps({
            "ts_ms": self.ts_ms,
            "person_count": self.person_count,
            "capacity": self.capacity,
            "confidence_avg": self.confidence_avg,
        })

# ---------- shared state ----------
STOP = threading.Event()
PUBLISH_Q: queue.Queue[InferenceResult] = queue.Queue(maxsize=50)  # prevents RAM blow-up

# ---------- inference functions ----------
def open_capture(source):
    """Open a webcam index (int) or a video/stream path (str)."""
    cap = cv2.VideoCapture(int(source)) if isinstance(source, int) else cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open source: {source}")
    return cap

# ---------- inference thread ----------
def inference_loop(
    publish_q: queue.Queue,
    stop_evt: threading.Event,
    fps: float = 10.0,
    model_path: str = "",
    device: str = "cpu",
    source=0,
    imgsz: int = 416,
    conf: float = 0.25,
    drop_old_on_full: bool = True,
    debug_show: bool = False
):
    # init
    model = YOLO(model_path)
    cap = open_capture(source)

    prev_t = time.time()
    fps_smooth = 0.0

    # pacing: if fps <= 0 => run as fast as possible (no sleep pacing)
    use_pacing = fps is not None and fps > 0
    period = (1.0 / fps) if use_pacing else 0.0
    next_t = time.perf_counter()

    try:
        while not stop_evt.is_set():
            loop_start = time.perf_counter()

            # ---------- pacing ----------
            if use_pacing:
                now = time.perf_counter()
                if now < next_t:
                    time.sleep(next_t - now)
                next_t += period
            # ----------------------------------------------------------------------

            ok, frame = cap.read()
            if not ok:
                # camera ended / disconnected; exit thread
                break

            # ---------- YOLO predict ----------
            results = model.predict(
                source=frame,
                imgsz=imgsz,
                conf=conf,
                device=device,
                verbose=False,
            )
            r0 = results[0]

            # ---------- inference on GUI (only for debug, to keep low processing have it disabled) ----------
            if debug_show:
                annotated = r0.plot()
                cv2.imshow("YOLO", annotated)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    stop_evt.set()
                    break

            # person_count: count boxes (common for detection)
            # If your model is segmentation/pose etc, adjust accordingly.
            if getattr(r0, "boxes", None) is not None and r0.boxes is not None:
                person_count = int(len(r0.boxes))
                # optional: confidence avg
                try:
                    confs = r0.boxes.conf
                    confidence_avg = float(confs.mean().item()) if confs is not None and len(confs) else 0.0
                except Exception:
                    confidence_avg = 0.0
            else:
                person_count = 0
                confidence_avg = 0.0
            # --------------------------------------------------------

            # ---------- FPS smoothing (ported from old code) ----------
            now_s = time.time()
            inst_fps = 1.0 / max(now_s - prev_t, 1e-6)
            prev_t = now_s
            fps_smooth = inst_fps if fps_smooth == 0.0 else (0.9 * fps_smooth + 0.1 * inst_fps)
            # ---------------------------------------------------------

            # package metadata for MQTT thread
            result = InferenceResult(
                ts_ms=int(now_s * 1000),
                person_count=person_count,
                capacity=40, #TODO: Get proper capacity
                confidence_avg=confidence_avg,
                # if you want to include fps, add a field in InferenceResult
                # fps=float(fps_smooth),
            )

            # push newest; keep real-time by dropping old if full
            try:
                publish_q.put_nowait(result)
            except queue.Full:
                if drop_old_on_full:
                    try:
                        _ = publish_q.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        publish_q.put_nowait(result)
                    except queue.Full:
                        pass

    finally:
        try:
            cap.release()
            if debug_show:
                cv2.destroyAllWindows()
        except Exception:
            pass

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
