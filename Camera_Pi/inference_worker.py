import queue, threading, time, cv2, json
from config import ROIS
from dataclasses import dataclass
from ultralytics import YOLO

# ---------- data model ----------
@dataclass
class InferenceResult:
    ts_ms: int
    # person_count: int
    total_count: int
    seated_count: int
    standing_count: int
    roi_counts: dict
    capacity: int
    confidence_avg: float
    occupancy_ratio: float
    cabin_status: str
    

    def to_json(self) -> str:
        return json.dumps({
            "ts_ms": self.ts_ms,
            # "person_count": self.person_count,
            "total_count": self.total_count,
            "seated_count": self.seated_count,
            "standing_count": self.standing_count,
            "roi_counts": self.roi_counts,
            "capacity": self.capacity,
            "confidence_avg": self.confidence_avg,
            "occupancy_ratio": self.occupancy_ratio,
            "cabin_status": self.cabin_status,
            
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

#DENNIS - helper function to compute occupancy ratio and status based on people count and capacity
def compute_cabin_status(people_count, capacity):
    if capacity <= 0:
        return 0.0, "UNKNOWN"

    ratio = people_count / capacity

    if people_count == 0:
        status = "EMPTY"
    elif ratio < 0.25:
        status = "LOW"
    elif ratio < 0.6:
        status = "MEDIUM"
    elif ratio < 0.9:
        status = "HIGH"
    else:
        status = "FULL"

    return ratio, status



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
    conf: float = 0.45, #0.25 is default in YOLOv8, but can be tuned for better precision/recall balance
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
                # for box in r0.boxes:
                #     full_frame_count += 1

                #     try:
                #         confidence_vals.append(float(box.conf[0].item()))
                #     except Exception:
                #         pass

                #     x1, y1, x2, y2 = box.xyxy[0].tolist()
                #     cx = int((x1 + x2) / 2)
                #     cy = int((y1 + y2) / 2)
                frame_h, frame_w = frame.shape[:2]

                for box in r0.boxes:

                    score = float(box.conf[0].item())

                    # STRICT CONFIDENCE FILTER
                    if score < 0.60:
                        continue

                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    bw = x2 - x1
                    bh = y2 - y1
                    area = bw * bh

                    # REMOVE VERY SMALL DETECTIONS
                    if area < frame_w * frame_h * 0.01:
                        continue

                    # REMOVE WIDE OBJECTS (chairs, tables)
                    aspect_ratio = bw / max(bh, 1)
                    if aspect_ratio > 1.3:
                        continue

                    full_frame_count += 1
                    confidence_vals.append(score)

                    # use bottom center for ROI
                    cx = int((x1 + x2) / 2)
                    cy = int(y2)

                    for roi_name, roi_poly in ROIS.items():
                        if point_in_polygon((cx, cy), roi_poly):
                            roi_counts[roi_name] += 1
                confidence_avg = sum(confidence_vals) / len(confidence_vals) if confidence_vals else 0.0
            else:
                full_frame_count = 0
                roi_counts = {name: 0 for name in ROIS}
                confidence_avg = 0.0
            # seated / standing split
            seated_count = sum(roi_counts.values())
            standing_count = max(0, full_frame_count - seated_count)

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
                    f"Total: {full_frame_count}",
                    (20, y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 255),
                    2
                )
                y += 30

                cv2.putText(
                    annotated,
                    f"Seated: {seated_count}",
                    (20, y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 255),
                    2
                )
                y += 30

                cv2.putText(
                    annotated,
                    f"Standing: {standing_count}",
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

            # DENNIS - compute occupancy ratio and status based on people count and capacity
            capacity = 40
            cabin_people = full_frame_count

            occupancy_ratio, cabin_status = compute_cabin_status(
                cabin_people,
                capacity
            )



            # package metadata for MQTT thread
            result = InferenceResult(
                ts_ms=int(now_s * 1000),
                #person_count=cabin_people,
                total_count=full_frame_count,
                seated_count=seated_count,
                standing_count=standing_count,
                roi_counts=roi_counts,
                capacity=capacity,
                confidence_avg=confidence_avg,
                occupancy_ratio=occupancy_ratio,
                cabin_status=cabin_status,
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
