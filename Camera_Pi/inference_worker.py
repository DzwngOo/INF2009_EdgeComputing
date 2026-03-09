import queue, threading, time, cv2, json
from config import ROIS
from dataclasses import dataclass
from ultralytics import YOLO

# ---------- data model ----------
@dataclass
class InferenceResult:
    ts_ms: int
    person_count: int
    roi_counts: dict
    capacity: int
    confidence_avg: float

    def to_json(self) -> str:
        return json.dumps({
            "ts_ms": self.ts_ms,
            "person_count": self.person_count,
            "roi_counts": self.roi_counts,
            "capacity": self.capacity,
            "confidence_avg": self.confidence_avg,
        })


# ---------- inference functions ----------
def point_in_polygon(point, polygon):
    return cv2.pointPolygonTest(polygon, point, False) >= 0

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
    conf: float = 0.55, #0.25 is default in YOLOv8, but can be tuned for better precision/recall balance
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

            # count people in full frame and in ROI separately
            full_frame_count = 0
            roi_counts = {name: 0 for name in ROIS}
            confidence_vals = []

            if getattr(r0, "boxes", None) is not None and r0.boxes is not None:
                for box in r0.boxes:
                    full_frame_count += 1

                    try:
                        confidence_vals.append(float(box.conf[0].item()))
                    except Exception:
                        pass

                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    cx = int((x1 + x2) / 2)
                    cy = int((y1 + y2) / 2)

                    for roi_name, roi_poly in ROIS.items():
                        if point_in_polygon((cx, cy), roi_poly):
                            roi_counts[roi_name] += 1
                confidence_avg = sum(confidence_vals) / len(confidence_vals) if confidence_vals else 0.0
            else:
                full_frame_count = 0
                roi_counts = {name: 0 for name in ROIS}
                confidence_avg = 0.0

            # ---------- inference on GUI (only for debug, to keep low processing have it disabled) ----------
            # If GUI enabled, send annotated frame to main thread
            if debug_show and display_q is not None:
                annotated = r0.plot()
                for roi_name, roi_poly in ROIS.items():
                    cv2.polylines(annotated, [roi_poly], isClosed=True, color=(0, 255, 255), thickness=2)
                # draw counts once
                y = 30
                cv2.putText(
                    annotated,
                    f"Full: {full_frame_count}",
                    (20, y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 255),
                    2
                )
                y += 30
                for roi_name, count in roi_counts.items():
                    cv2.putText(
                        annotated,
                        f"{roi_name}: {count}",
                        (20, y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 255, 255),
                        2
                    )
                    y += 30

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
                person_count=full_frame_count,
                roi_counts=roi_counts,
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
