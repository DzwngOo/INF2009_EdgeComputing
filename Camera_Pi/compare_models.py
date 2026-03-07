import argparse
import csv
import statistics
import time
from pathlib import Path

from ultralytics import YOLO

from benchmark_models import CpuSampler, count_people, open_capture, percentile, warmup_model


def load_labels(path: str | None) -> dict[int, int]:
    if not path:
        return {}

    labels: dict[int, int] = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            labels[int(row["frame_idx"])] = int(row["true_count"])
    return labels


def benchmark_one_model(
    model_name: str,
    model_path: str,
    source: str,
    imgsz: int,
    conf: float,
    frames: int,
    warmup: int,
):
    resolved_model_path = str(Path(model_path).resolve())
    model = YOLO(resolved_model_path)
    warmup_model(model, source, imgsz, conf, warmup)

    cap = open_capture(source)
    sampler = CpuSampler(interval=0.2)
    sampler.start()

    inference_ms_values: list[float] = []
    confidence_values: list[float] = []
    start_wall = time.perf_counter()

    try:
        frame_idx = 0
        while frame_idx < frames:
            ok, frame = cap.read()
            if not ok:
                break

            t0 = time.perf_counter()
            results = model.predict(
                source=frame,
                imgsz=imgsz,
                conf=conf,
                classes=[0],
                max_det=50,
                verbose=False,
            )
            infer_ms = (time.perf_counter() - t0) * 1000.0

            _, confidence_avg = count_people(results[0])
            confidence_values.append(confidence_avg)
            inference_ms_values.append(infer_ms)
            frame_idx += 1
    finally:
        elapsed_s = time.perf_counter() - start_wall
        sampler.stop()
        sampler.join(timeout=1.0)
        cap.release()

    avg_ms = statistics.mean(inference_ms_values) if inference_ms_values else 0.0
    p50_ms = statistics.median(inference_ms_values) if inference_ms_values else 0.0
    p95_ms = percentile(inference_ms_values, 95)
    avg_confidence = statistics.mean(confidence_values) if confidence_values else 0.0
    fps_value = (len(inference_ms_values) / elapsed_s) if elapsed_s > 0 else 0.0
    avg_system_cpu = statistics.mean(sampler.system_samples) if sampler.system_samples else 0.0
    avg_process_cpu = statistics.mean(sampler.process_samples) if sampler.process_samples else 0.0
    avg_machine_share = (
        statistics.mean(sampler.process_machine_share_samples)
        if sampler.process_machine_share_samples
        else 0.0
    )

    summary = {
        "model": model_name,
        "model_path": resolved_model_path,
        "frames": len(inference_ms_values),
        "avg_ms": round(avg_ms, 2),
        "p50_ms": round(p50_ms, 2),
        "p95_ms": round(p95_ms, 2),
        "avg_confidence": round(avg_confidence, 4),
        "fps": round(fps_value, 2),
        "system_cpu": round(avg_system_cpu, 2),
        "process_cpu": round(avg_process_cpu, 2),
        "machine_cpu_share": round(avg_machine_share, 2),
    }

    return summary


def print_table(rows: list[dict]):
    columns = [
        ("model", "Model"),
        ("avg_ms", "Avg ms"),
        ("p95_ms", "P95 ms"),
        ("avg_confidence", "Avg conf"),
        ("fps", "FPS"),
        ("system_cpu", "System CPU %"),
        ("process_cpu", "Proc CPU %"),
        ("machine_cpu_share", "Machine share %"),
    ]

    widths = []
    for key, title in columns:
        width = len(title)
        for row in rows:
            width = max(width, len(str(row.get(key, ""))))
        widths.append(width)

    header = " | ".join(title.ljust(width) for (_, title), width in zip(columns, widths))
    divider = "-+-".join("-" * width for width in widths)
    print(header)
    print(divider)
    for row in rows:
        print(" | ".join(str(row.get(key, "")).ljust(width) for (key, _), width in zip(columns, widths)))


def main():
    parser = argparse.ArgumentParser(description="Run the same benchmark across multiple YOLO models.")
    parser.add_argument(
        "--models",
        nargs="+",
        required=True,
        help="One or more model specs in the form name=path",
    )
    parser.add_argument("--source", required=True, help="Video file path for repeatable comparisons")
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--warmup", type=int, default=30)
    parser.add_argument("--summary-out", help="Optional CSV path for the final side-by-side summary")
    args = parser.parse_args()
    summaries = []

    for spec in args.models:
        if "=" not in spec:
            raise ValueError(f"Invalid model spec '{spec}'. Use name=path.")
        model_name, model_path = spec.split("=", 1)
        print(f"\nRunning benchmark for {model_name}...")
        summaries.append(
            benchmark_one_model(
                model_name=model_name,
                model_path=model_path,
                source=args.source,
                imgsz=args.imgsz,
                conf=args.conf,
                frames=args.frames,
                warmup=args.warmup,
            )
        )

    print("\n=== Side-by-Side Summary ===")
    print_table(summaries)

    if args.summary_out:
        output_path = Path(args.summary_out).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(summaries[0].keys()))
            writer.writeheader()
            writer.writerows(summaries)
        print(f"\nSummary CSV saved to: {output_path}")


if __name__ == "__main__":
    main()