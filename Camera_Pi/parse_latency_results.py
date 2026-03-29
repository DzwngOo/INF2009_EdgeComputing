#!/usr/bin/env python3
"""
Parse latency_results.csv and calculate end-to-end latency automatically.
"""

from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = int(round((p / 100.0) * (len(values) - 1)))
    idx = max(0, min(idx, len(values) - 1))
    return float(values[idx])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute camera-side and full estimated end-to-end latency from latency_results.csv.",
    )
    parser.add_argument(
        "--in",
        dest="in_csv",
        default="latency_results.csv",
        help="Input CSV from measure_latency.py (default: latency_results.csv).",
    )
    parser.add_argument(
        "--stage4-ms",
        type=float,
        default=20.0,
        help="Expected Stage 4 (ultrasonic poll) latency in ms (default: 20).",
    )
    parser.add_argument(
        "--stage7-ms",
        type=float,
        default=500.0,
        help="Expected Stage 7 (LoRa TX) latency in ms (default: 500).",
    )
    parser.add_argument(
        "--stage8_9-ms",
        type=float,
        default=250.0,
        help="Expected Stages 8-9 (cloud+dashboard) latency in ms (default: 250).",
    )
    parser.add_argument(
        "--budget-ms",
        type=float,
        default=2000.0,
        help="End-to-end budget in ms (default: 2000).",
    )
    return parser.parse_args()


def load_camera_e2e_ms(path: Path) -> list[float]:
    values: list[float] = []
    fallback_cols = ("capture_preprocess_ms", "inference_ms", "mqtt_publish_ms")
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):
            if row.get("end_to_end_ms"):
                values.append(float(row["end_to_end_ms"]))
            else:
                if not any(col in row for col in fallback_cols):
                    raise ValueError(
                        f"Row {i} is missing end_to_end_ms and fallback stage columns: {fallback_cols}",
                    )
                cap = float(row.get("capture_preprocess_ms", 0.0))
                inf = float(row.get("inference_ms", 0.0))
                mqtt = float(row.get("mqtt_publish_ms", 0.0))
                values.append(cap + inf + mqtt)
    if not values:
        raise ValueError(f"No latency rows found in {path}")
    return values


def main() -> None:
    args = parse_args()
    in_path = Path(args.in_csv).resolve()
    if not in_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {in_path}")

    camera_e2e_ms = load_camera_e2e_ms(in_path)
    remote_expected_ms = args.stage4_ms + args.stage7_ms + args.stage8_9_ms
    full_e2e_ms = [v + remote_expected_ms for v in camera_e2e_ms]

    camera_mean = statistics.mean(camera_e2e_ms)
    camera_p99 = percentile(camera_e2e_ms, 99)
    full_mean = statistics.mean(full_e2e_ms)
    full_p99 = percentile(full_e2e_ms, 99)

    within_budget = full_mean <= args.budget_ms
    marker = "✓" if within_budget else "✗"

    print("Latency Parser Summary")
    print("=" * 56)
    print(f"Input CSV:            {in_path}")
    print(f"Samples:              {len(camera_e2e_ms)}")
    print()
    print(f"Camera E2E mean/p99:  {camera_mean:.1f} / {camera_p99:.1f} ms")
    print(f"Added remote stages:  {remote_expected_ms:.1f} ms (S4+S7+S8-9)")
    print(f"Full E2E mean/p99:    {full_mean:.1f} / {full_p99:.1f} ms")
    print(f"Budget check:         {marker}  target ≤ {args.budget_ms:.0f} ms")


if __name__ == "__main__":
    main()
