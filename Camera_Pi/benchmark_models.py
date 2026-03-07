import argparse
import csv
import statistics
import threading
import time
from pathlib import Path

import cv2
import psutil
from ultralytics import YOLO


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    index = int(round((p / 100.0) * (len(values) - 1)))
    index = max(0, min(index, len(values) - 1))
    return float(values[index])


class CpuSampler(threading.Thread):
    def __init__(self, interval: float = 0.2):
        super().__init__(daemon=True)
        self.interval = interval
        self.stop_evt = threading.Event()
        self.proc = psutil.Process()
        self.system_samples: list[float] = []
        self.process_samples: list[float] = []
        self.process_machine_share_samples: list[float] = []

    def run(self):
        cpu_count = psutil.cpu_count(logical=True) or 1
        self.proc.cpu_percent(None)
        psutil.cpu_percent(None)

        while not self.stop_evt.is_set():
            time.sleep(self.interval)
            system_cpu = psutil.cpu_percent(None)
            process_cpu = self.proc.cpu_percent(None)

            self.system_samples.append(system_cpu)
            self.process_samples.append(process_cpu)
            self.process_machine_share_samples.append(process_cpu / cpu_count)

    def stop(self):
        self.stop_evt.set()


def open_capture(source: str):
    if source.isdigit():
        cap = cv2.VideoCapture(int(source))
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open camera index: {source}")
        return cap

    source_path = Path(source)
    if not source_path.is_absolute():
        candidates = [
            Path.cwd() / source_path,
            Path(__file__).resolve().parent / source_path,
            Path(__file__).resolve().parent.parent / source_path,
        ]
        for candidate in candidates:
            if candidate.exists():
                source_path = candidate.resolve()
                break

    if not source_path.exists():
        raise RuntimeError(
            "Failed to open source: "
            f"{source}. File not found. Use an absolute path, a valid path relative to Camera_Pi, "
            "or a camera index like 0."
        )

    cap = cv2.VideoCapture(str(source_path))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open source: {source_path}")
    return cap


def count_people(result) -> tuple[int, float]:
    boxes = getattr(result, "boxes", None)
    if boxes is None or boxes.cls is None:
        return 0, 0.0

    person_count = 0
    confidences = []
    names = result.names

    for idx, cls_id in enumerate(boxes.cls.tolist()):
        if names[int(cls_id)] == "person":
            person_count += 1
            if boxes.conf is not None and idx < len(boxes.conf):
                confidences.append(float(boxes.conf[idx]))

    confidence_avg = sum(confidences) / len(confidences) if confidences else 0.0
    return person_count, confidence_avg


def warmup_model(model, source: str, imgsz: int, conf: float, warmup_frames: int):
    if warmup_frames <= 0:
        return

    cap = open_capture(source)
    try:
        warmed = 0
        while warmed < warmup_frames:
            ok, frame = cap.read()
            if not ok:
                break
            _ = model.predict(
                source=frame,
                imgsz=imgsz,
                conf=conf,
                classes=[0],
                max_det=50,
                verbose=False,
            )
            warmed += 1
    finally:
        cap.release()


def main():
    parser = argparse.ArgumentParser(description="Benchmark YOLO models on the same input source.")
    parser.add_argument("--model", required=True, help="Path to .pt file or exported NCNN model folder")
    parser.add_argument("--source", required=True, help="Video file path recommended for repeatable testing")
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--warmup", type=int, default=30)
    parser.add_argument("--output", default="benchmark_results.csv")
    args = parser.parse_args()

    model_path = str(Path(args.model).resolve())
    output_path = Path(args.output).resolve()

    print(f"Loading model: {model_path}")
    model = YOLO(model_path)
    warmup_model(model, args.source, args.imgsz, args.conf, args.warmup)

    cap = open_capture(args.source)
    sampler = CpuSampler(interval=0.2)
    sampler.start()

    rows = []
    inference_ms_values: list[float] = []
    confidence_values: list[float] = []
    start_wall = time.perf_counter()

    try:
        frame_idx = 0
        while frame_idx < args.frames:
            ok, frame = cap.read()
            if not ok:
                break

            t0 = time.perf_counter()
            results = model.predict(
                source=frame,
                imgsz=args.imgsz,
                conf=args.conf,
                classes=[0],
                max_det=50,
                verbose=False,
            )
            infer_ms = (time.perf_counter() - t0) * 1000.0

            person_count, confidence_avg = count_people(results[0])
            rows.append({
                "frame_idx": frame_idx,
                "person_count": person_count,
                "confidence_avg": round(confidence_avg, 4),
                "inference_ms": round(infer_ms, 3),
            })
            inference_ms_values.append(infer_ms)
            confidence_values.append(confidence_avg)
            frame_idx += 1
    finally:
        elapsed_s = time.perf_counter() - start_wall
        sampler.stop()
        sampler.join(timeout=1.0)
        cap.release()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["frame_idx", "person_count", "confidence_avg", "inference_ms"],
        )
        writer.writeheader()
        writer.writerows(rows)

    avg_ms = statistics.mean(inference_ms_values) if inference_ms_values else 0.0
    p50_ms = statistics.median(inference_ms_values) if inference_ms_values else 0.0
    p95_ms = percentile(inference_ms_values, 95)
    avg_confidence = statistics.mean(confidence_values) if confidence_values else 0.0
    avg_fps = (len(inference_ms_values) / elapsed_s) if elapsed_s > 0 else 0.0

    avg_system_cpu = statistics.mean(sampler.system_samples) if sampler.system_samples else 0.0
    avg_process_cpu = statistics.mean(sampler.process_samples) if sampler.process_samples else 0.0
    avg_machine_share = (
        statistics.mean(sampler.process_machine_share_samples)
        if sampler.process_machine_share_samples
        else 0.0
    )

    print("\n=== Benchmark Summary ===")
    print(f"Frames measured             : {len(inference_ms_values)}")
    print(f"Average inference latency   : {avg_ms:.2f} ms")
    print(f"Median inference latency    : {p50_ms:.2f} ms")
    print(f"P95 inference latency       : {p95_ms:.2f} ms")
    print(f"Average confidence score    : {avg_confidence:.4f}")
    print(f"Effective throughput        : {avg_fps:.2f} FPS")
    print(f"Average system CPU          : {avg_system_cpu:.2f}%")
    print(f"Average Python process CPU  : {avg_process_cpu:.2f}%")
    print(f"Average machine CPU share   : {avg_machine_share:.2f}%")
    print(f"Per-frame CSV              : {output_path}")


if __name__ == "__main__":
    main()