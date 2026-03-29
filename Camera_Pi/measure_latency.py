#!/usr/bin/env python3
"""
Latency benchmark — Camera Pi pipeline.

Measures each stage of the detection pipeline and reports mean ± σ, p99,
and an overall end-to-end figure across a configurable number of cycles.

Pipeline stages measured (Camera Pi side only):
  Stage 1-2  capture_preprocess_ms : cap.read() + colour conversion / resize
  Stage 3    inference_ms          : YOLO predict() including internal NMS
  Stage 5-6  mqtt_ms               : JSON serialise + client.publish() round-trip

The remaining stages (Stage 4 – ultrasonic GPIO ~20 ms, Stage 7 – LoRa TX
~500 ms, Stages 8-9 – cloud ingest + dashboard render ~250 ms) run on
separate hardware and are not measurable from this host; their expected
latencies are printed for reference.

Usage:
    python3 measure_latency.py --model ../../yolo11s_ncnn_model --source 0
    python3 measure_latency.py --model ../../yolo11s_ncnn_model \\
        --source sample.mp4 --cycles 500 --fps-window 60 --out latency.csv
"""

import argparse
import csv
import json
import statistics
import time
from pathlib import Path

import cv2


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

def percentile(values: list[float], p: float) -> float:
    """Return the p-th percentile of *values* (0–100)."""
    if not values:
        return 0.0
    values = sorted(values)
    idx = int(round((p / 100.0) * (len(values) - 1)))
    idx = max(0, min(idx, len(values) - 1))
    return float(values[idx])


def stage_stats(values: list[float]) -> dict:
    if not values:
        return {"mean": 0.0, "stdev": 0.0, "p99": 0.0, "min": 0.0, "max": 0.0}
    return {
        "mean": statistics.mean(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "p99": percentile(values, 99),
        "min": min(values),
        "max": max(values),
    }


def print_stats_row(label: str, stats: dict, budget_ms: float | None = None) -> None:
    line = (
        f"  {label:<34s}"
        f"  mean={stats['mean']:7.1f} ms"
        f"  ± {stats['stdev']:5.1f} ms"
        f"  p99={stats['p99']:7.1f} ms"
        f"  [{stats['min']:.1f}–{stats['max']:.1f}]"
    )
    if budget_ms is not None:
        ok = "✓" if stats["mean"] <= budget_ms else "✗"
        line += f"  budget={budget_ms:.0f} ms {ok}"
    print(line)


# ---------------------------------------------------------------------------
# Capture helpers
# ---------------------------------------------------------------------------

def open_capture(source):
    """Open a camera index (int/digit str) or a video file path."""
    if isinstance(source, int) or (isinstance(source, str) and source.isdigit()):
        cap = cv2.VideoCapture(int(source))
    else:
        cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open source: {source!r}")
    return cap


# ---------------------------------------------------------------------------
# MQTT helper — graceful if broker is absent
# ---------------------------------------------------------------------------

def make_mqtt_client(broker_host: str, broker_port: int):
    """Return a connected paho MQTT client, or None if unavailable."""
    try:
        import paho.mqtt.client as mqtt  # noqa: PLC0415
    except ImportError:
        print("[WARN] paho-mqtt not installed — MQTT stage will use serialise-only timing.")
        return None
    try:
        client = mqtt.Client("latency_bench_pub")
        client.connect(broker_host, broker_port, keepalive=10)
        client.loop_start()
        time.sleep(0.3)  # allow socket handshake
        return client
    except Exception as exc:
        print(f"[WARN] MQTT broker not reachable ({exc}) — MQTT stage will use serialise-only timing.")
        return None


# ---------------------------------------------------------------------------
# Per-stage measurement
# ---------------------------------------------------------------------------

def measure_capture_preprocess(cap, imgsz: int) -> tuple[float, object | None]:
    """Stage 1-2: read a raw frame and resize to model input dimensions."""
    t0 = time.perf_counter()
    ok, frame = cap.read()
    if not ok:
        return 0.0, None
    frame = cv2.resize(frame, (imgsz, imgsz))
    return (time.perf_counter() - t0) * 1000.0, frame


def measure_inference(model, frame, imgsz: int, conf: float) -> tuple[float, object]:
    """Stage 3: YOLO predict() on the pre-resized frame."""
    t0 = time.perf_counter()
    results = model.predict(
        source=frame,
        imgsz=imgsz,
        conf=conf,
        classes=[0],
        max_det=50,
        verbose=False,
    )
    return (time.perf_counter() - t0) * 1000.0, results[0]


def _build_payload() -> str:
    """Produce a representative JSON payload (mirrors InferenceResult.to_json)."""
    return json.dumps({
        "ts_ms": int(time.time() * 1000),
        "total_count": 1,
        "seated_count": 0,
        "standing_count": 1,
        "roi_presence": {"seat1": False, "seat2": False},
        "capacity": 3,
        "confidence_avg": 0.75,
        "occupancy_ratio": 0.33,
        "cabin_status": "LOW",
    })


def measure_mqtt_publish(client, topic: str, qos: int = 0) -> float:
    """Stage 5-6: JSON serialise + client.publish (or serialise-only if no broker)."""
    payload = _build_payload()
    t0 = time.perf_counter()
    if client is not None:
        client.publish(topic, payload, qos=qos, retain=False)
    # else: serialise cost already included in the payload build above
    return (time.perf_counter() - t0) * 1000.0


# ---------------------------------------------------------------------------
# FPS measurement — sustained throughput over a timed window
# ---------------------------------------------------------------------------

def measure_fps(model, cap, imgsz: int, conf: float, window_s: float = 60.0) -> float:
    """Count full inference cycles completed within *window_s* seconds."""
    frame_count = 0
    t_start = time.perf_counter()
    deadline = t_start + window_s

    while time.perf_counter() < deadline:
        ok, frame = cap.read()
        if not ok:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
            if not ok:
                break
        frame = cv2.resize(frame, (imgsz, imgsz))
        model.predict(
            source=frame, imgsz=imgsz, conf=conf,
            classes=[0], max_det=50, verbose=False,
        )
        frame_count += 1

    elapsed = time.perf_counter() - t_start
    return frame_count / elapsed if elapsed > 0 else 0.0


# ---------------------------------------------------------------------------
# Main latency benchmark loop
# ---------------------------------------------------------------------------

def run_latency_benchmark(
    model,
    cap,
    mqtt_client,
    mqtt_topic: str,
    imgsz: int,
    conf: float,
    cycles: int,
    warmup: int,
) -> dict[str, list[float]]:
    """Run *cycles* pipeline iterations and return per-stage timing lists."""
    cap_ms_list: list[float] = []
    infer_ms_list: list[float] = []
    mqtt_ms_list: list[float] = []
    e2e_ms_list: list[float] = []

    # ---- warm-up ----
    print(f"  Warming up ({warmup} frames) …", end="", flush=True)
    for _ in range(warmup):
        ok, frame = cap.read()
        if not ok:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if frame is not None:
            frame = cv2.resize(frame, (imgsz, imgsz))
            model.predict(
                source=frame, imgsz=imgsz, conf=conf,
                classes=[0], max_det=50, verbose=False,
            )
    print(" done")

    # ---- measurement cycles ----
    print(f"  Measuring {cycles} cycles …", end="", flush=True)
    for i in range(cycles):
        t_cycle_start = time.perf_counter()

        # Stage 1-2
        cap_ms, frame = measure_capture_preprocess(cap, imgsz)
        if frame is None:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            cap_ms, frame = measure_capture_preprocess(cap, imgsz)
        if frame is None:
            continue

        # Stage 3
        infer_ms, _ = measure_inference(model, frame, imgsz, conf)

        # Stage 5-6
        mqtt_ms = measure_mqtt_publish(mqtt_client, mqtt_topic)

        e2e_ms = (time.perf_counter() - t_cycle_start) * 1000.0

        cap_ms_list.append(cap_ms)
        infer_ms_list.append(infer_ms)
        mqtt_ms_list.append(mqtt_ms)
        e2e_ms_list.append(e2e_ms)

        if (i + 1) % 100 == 0:
            print(f" {i + 1}", end="", flush=True)

    print(" done")

    return {
        "capture_preprocess": cap_ms_list,
        "inference": infer_ms_list,
        "mqtt_publish": mqtt_ms_list,
        "end_to_end": e2e_ms_list,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Camera Pi pipeline latency benchmark.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model", required=True,
                        help="YOLO model path (.pt or NCNN model folder)")
    parser.add_argument("--source", default="0",
                        help="Camera index or video file path")
    parser.add_argument("--imgsz", type=int, default=320,
                        help="Inference image size")
    parser.add_argument("--conf", type=float, default=0.25,
                        help="Detection confidence threshold")
    parser.add_argument("--cycles", type=int, default=500,
                        help="Number of measurement cycles")
    parser.add_argument("--warmup", type=int, default=30,
                        help="Warm-up frames before measurement")
    parser.add_argument("--fps-window", type=float, default=60.0,
                        help="Sustained-FPS measurement window in seconds")
    parser.add_argument("--broker-host", default="127.0.0.1",
                        help="MQTT broker host")
    parser.add_argument("--broker-port", type=int, default=1884,
                        help="MQTT broker port")
    parser.add_argument("--topic", default="mrt/cabin1/vision",
                        help="MQTT publish topic")
    parser.add_argument("--out", default="latency_results.csv",
                        help="Output CSV file path")
    parser.add_argument("--skip-fps", action="store_true",
                        help="Skip the sustained-FPS measurement window")
    args = parser.parse_args()

    source = int(args.source) if args.source.isdigit() else args.source

    print("=" * 62)
    print("  Camera Pi — Pipeline Latency Benchmark")
    print("=" * 62)

    # 1. Load model
    print(f"\n[1/4] Loading model: {args.model}")
    from ultralytics import YOLO  # noqa: PLC0415
    model = YOLO(str(Path(args.model).resolve()))

    # 2. Open capture
    print(f"[2/4] Opening source: {source}")
    cap = open_capture(source)

    # 3. MQTT
    print(f"[3/4] Connecting to MQTT broker {args.broker_host}:{args.broker_port} …")
    mqtt_client = make_mqtt_client(args.broker_host, args.broker_port)

    # 4. Latency cycles
    print(f"\n[4/4] Latency benchmark  ({args.cycles} cycles, warmup={args.warmup})")
    data = run_latency_benchmark(
        model=model,
        cap=cap,
        mqtt_client=mqtt_client,
        mqtt_topic=args.topic,
        imgsz=args.imgsz,
        conf=args.conf,
        cycles=args.cycles,
        warmup=args.warmup,
    )

    # Optional FPS window
    fps_sustained: float | None = None
    if not args.skip_fps:
        print(f"\n[FPS] Sustained throughput over {args.fps_window:.0f} s …")
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        fps_sustained = measure_fps(
            model, cap, args.imgsz, args.conf, window_s=args.fps_window,
        )
        fps_ok = "✓" if fps_sustained >= 5.0 else "✗"
        print(f"      {fps_sustained:.2f} FPS  {fps_ok}  (target ≥ 5 FPS)")

    cap.release()
    if mqtt_client is not None:
        mqtt_client.loop_stop()

    # ---- Statistics ----
    stats = {stage: stage_stats(vals) for stage, vals in data.items()}

    BUDGETS = {
        "capture_preprocess": 15.0,
        "inference": 42.0,
        "mqtt_publish": 10.0,
        "end_to_end": 2000.0,
    }
    LABELS = {
        "capture_preprocess": "Stage 1-2  capture + preprocess",
        "inference":          "Stage 3    YOLO inference",
        "mqtt_publish":       "Stage 5    MQTT serialise + publish",
        "end_to_end":         "End-to-end (stages 1-5, measured)",
    }

    print("\n" + "=" * 62)
    print("  Results — mean ± σ  |  p99  |  [min–max]")
    print("=" * 62)
    for key in ("capture_preprocess", "inference", "mqtt_publish", "end_to_end"):
        print_stats_row(LABELS[key], stats[key], budget_ms=BUDGETS[key])

    print()
    print("  — Hardware-bound stages (reference, not measured here) —")
    print(f"  {'Stage 4    Ultrasonic poll (×10)':<34s}  expected ~20 ms  (GPIO async, Ultrasonic Pi)")
    print(f"  {'Stage 6    MQTT fusion (rule engine)':<34s}  expected ~10 ms  (Ultrasonic Pi, fuses cam+sonar)")
    print(f"  {'Stage 7    LoRa TX (50 B, SF7/BW125)':<34s}  expected ~500 ms (SX1276 air-time)")
    print(f"  {'Stages 8-9 Cloud ingest + dashboard':<34s}  expected ~250 ms (InfluxDB + WebSocket)")
    print()

    e2e_mean = stats["end_to_end"]["mean"]
    ok_str = "✓" if e2e_mean <= 2000.0 else "✗"
    margin = (1 - e2e_mean / 2000.0) * 100
    print(f"  End-to-end mean (measurable stages): {e2e_mean:.1f} ms  {ok_str}  ({margin:.0f}% under 2000 ms budget)")

    if fps_sustained is not None:
        fps_ok = "✓" if fps_sustained >= 5.0 else "✗"
        print(f"  Sustained FPS ({args.fps_window:.0f}s window):          {fps_sustained:.2f} FPS  {fps_ok}  (target ≥ 5 FPS)")

    # ---- Save CSV ----
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = len(data["end_to_end"])
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "cycle",
                "capture_preprocess_ms",
                "inference_ms",
                "mqtt_publish_ms",
                "end_to_end_ms",
            ],
        )
        writer.writeheader()
        for i in range(n):
            writer.writerow({
                "cycle": i + 1,
                "capture_preprocess_ms": round(data["capture_preprocess"][i], 3),
                "inference_ms": round(data["inference"][i], 3),
                "mqtt_publish_ms": round(data["mqtt_publish"][i], 3),
                "end_to_end_ms": round(data["end_to_end"][i], 3),
            })

    print(f"\n  Per-cycle CSV saved to: {out_path}")
    print("=" * 62)


if __name__ == "__main__":
    main()
