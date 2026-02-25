#!/usr/bin/env python3
# main.py
import time

import cv2
from ultralytics import YOLO

import config


def open_capture(source):
    """Open a webcam index (int) or a video/stream path (str)."""
    cap = cv2.VideoCapture(int(source)) if isinstance(source, int) else cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open source: {source}")
    return cap


def main():
    # ----- Fixed settings (no CLI arguments) -----
    model_path = config.MODEL
    device = config.DEVICE

    source = config.SOURCE
    imgsz = config.IMGSZ
    conf = config.CONF

    # Always show window
    show = True
    max_fps = float(getattr(config, "MAX_FPS", 0.0))
    # --------------------------------------------

    model = YOLO(model_path)
    cap = open_capture(source)

    prev_t = time.time()
    fps_smooth = 0.0

    try:
        while True:
            loop_start = time.time()

            ok, frame = cap.read()
            if not ok:
                break

            results = model.predict(
                source=frame,
                imgsz=imgsz,
                conf=conf,
                device=device,
                verbose=False,
            )

            annotated = results[0].plot()

            now = time.time()
            inst_fps = 1.0 / max(now - prev_t, 1e-6)
            prev_t = now
            fps_smooth = inst_fps if fps_smooth == 0.0 else (0.9 * fps_smooth + 0.1 * inst_fps)

            cv2.putText(
                annotated,
                f"FPS: {fps_smooth:.1f}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

            cv2.imshow("YOLO26 (Raspberry Pi)", annotated)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

            if max_fps and max_fps > 0:
                target_dt = 1.0 / max_fps
                elapsed = time.time() - loop_start
                if elapsed < target_dt:
                    time.sleep(target_dt - elapsed)

    finally:
        cap.release()
        if show:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
