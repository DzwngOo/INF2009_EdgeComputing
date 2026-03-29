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
    roi_presence: dict
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
            "roi_presence": self.roi_presence,
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
    elif ratio < 0.4:
        status = "LOW"
    elif ratio < 0.6:
        status = "MEDIUM"
    elif ratio < 0.9:
        status = "HIGH"
    else:
        status = "FULL"

    # if people_count == 0:
    #     status = "EMPTY"
    # elif ratio < 0.25:
    #     status = "LOW"
    # elif ratio < 0.6:
    #     status = "MEDIUM"
    # elif ratio < 0.9:
    #     status = "HIGH"
    # else:
    #     status = "FULL"

    return ratio, status

def process_frame(frame, model, roi_presence, conf=0.45, img_size=416):
    """Process each frame: detect objects and count people in full frame and ROI."""
    results = model.predict(source=frame, imgsz=img_size, conf=conf, classes=[0], max_det=50, verbose=False)
    r0 = results[0]
    full_frame_count = 0        # count people in full frame and in ROI separately
    confidence_vals = []

    if r0.boxes:
        frame_h, frame_w = frame.shape[:2]
        for box in r0.boxes:
            score = float(box.conf[0].item())
            if score < 0.60:    # STRICT CONFIDENCE FILTER
                continue

            x1, y1, x2, y2 = box.xyxy[0].tolist()
            bw = x2 - x1
            bh = y2 - y1
            area = bw * bh

            if area < frame_w * frame_h * 0.01: # REMOVE VERY SMALL DETECTIONS
                continue

            aspect_ratio = bw / max(bh, 1) 
            if aspect_ratio > 1.3: # REMOVE WIDE OBJECTS (chairs, tables)
                continue

            full_frame_count += 1
            confidence_vals.append(score)

            # Count people in ROI
            cx = int((x1 + x2) / 2)
            cy = int((y1 + y2) / 2)
            for roi_name, roi_poly in ROIS.items():
                if point_in_polygon((cx, cy), roi_poly):
                    roi_presence[roi_name] = True

    confidence_avg = sum(confidence_vals) / len(confidence_vals) if confidence_vals else 0.0
    return full_frame_count, roi_presence, confidence_avg, r0

def annotate_frame(frame, r0, full_frame_count, seated_count, standing_count, roi_presence, debug_show=False):
    """Add annotations on frame for debugging."""
    if debug_show:
        y = 30
        cv2.putText(frame, f"Total: {full_frame_count}", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        y += 30
        cv2.putText(frame, f"Seated: {seated_count}", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        y += 30
        cv2.putText(frame, f"Standing: {standing_count}", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        y += 30

        for roi_name, present in roi_presence.items():
            cv2.putText(frame, f"{roi_name}: {present}", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            y += 30

        # False = yellow, True = blue
        for roi_name, roi_poly in ROIS.items():
            color = (255, 0, 0) if roi_presence[roi_name] else (0, 255, 255)
            cv2.polylines(frame, [roi_poly], isClosed=True, color=color, thickness=2)

        # Draw bounding boxes for each detected person
        if r0.boxes:
            for box in r0.boxes:
                # Get bounding box coordinates and draw it on the frame
                x1, y1, x2, y2 = box.xyxy[0].tolist()

                # Draw the bounding box in blue (or any color you prefer)
                cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (255, 0, 0), 2)  # BGR color for blue

                # Optionally, add confidence score on the bounding box
                confidence = float(box.conf[0].item())
                cv2.putText(frame, f"{confidence:.2f}", (int(x1), int(y1)-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    return frame

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

    use_pacing = fps is not None and fps > 0    # pacing: if fps <= 0 => run as fast as possible (no sleep pacing)
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

            roi_presence = {name: False for name in ROIS}   # start every ROI as False
            full_frame_count, roi_presence, confidence_avg, r0 = process_frame(frame, model, roi_presence, conf, imgsz)
            # seated / standing split
            seated_count = sum(roi_presence.values())
            standing_count = max(0, full_frame_count - seated_count)

            # DENNIS - compute occupancy ratio and status based on people count and capacity
            capacity = 3
            cabin_people = full_frame_count
            occupancy_ratio, cabin_status = compute_cabin_status(
                cabin_people,
                capacity
            )

            # package metadata for MQTT thread
            result = InferenceResult(
                ts_ms=int(time.time() * 1000),
                #person_count=cabin_people,
                total_count=full_frame_count,
                seated_count=seated_count,
                standing_count=standing_count,
                roi_presence=roi_presence,
                capacity=capacity,
                confidence_avg=confidence_avg,
                occupancy_ratio=occupancy_ratio,
                cabin_status=cabin_status,
            )

            # Push result to publish queue
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

            # ---------- inference on GUI (only for debug, to keep low processing have it disabled) ----------
            # Annotate and show frame if required
            if display_q is not None:
                annotated_frame = annotate_frame(frame, r0, full_frame_count, seated_count, standing_count, roi_presence, debug_show)
                try:
                    display_q.put_nowait(annotated_frame)
                except queue.Full:
                    pass

    finally:
        try:
            cap.release()
        except Exception:
            pass
