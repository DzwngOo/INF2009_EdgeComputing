import queue, threading, time, cv2, json
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
    display_q: queue.Queue | None = None,
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
            # ---------- pacing ----------
            if use_pacing:
                now = time.perf_counter()
                if now < next_t:
                    time.sleep(next_t - now)
                next_t += period
            # ----------------------------------------------------------------------

            ok, frame = cap.read()
            if not ok:
                break

            # ---------- YOLO predict ----------
            results = model.predict(
                source=frame,
                imgsz=imgsz,
                conf=conf,
                device=device,
                classes=[0],      
                max_det=50,       # cap max detection
                verbose=False,
            )
            r0 = results[0]

            # person_count: count boxes (common for detection)
            if getattr(r0, "boxes", None) is not None and r0.boxes is not None:
                person_count = int(len(r0.boxes))
                try:
                    confs = r0.boxes.conf
                    confidence_avg = float(confs.mean().item()) if confs is not None and len(confs) else 0.0
                except Exception:
                    confidence_avg = 0.0
            else:
                person_count = 0
                confidence_avg = 0.0

            # ---------- inference on GUI (only for debug, to keep low processing have it disabled) ----------
            # If GUI enabled, send annotated frame to main thread
            if debug_show and display_q is not None:
                annotated = r0.plot()
                try:
                    display_q.put_nowait(annotated)
                except queue.Full:
                    # drop old frame to keep it “live”
                    try:
                        _ = display_q.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        display_q.put_nowait(annotated)
                    except queue.Full:
                        pass

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
        except Exception:
            pass
