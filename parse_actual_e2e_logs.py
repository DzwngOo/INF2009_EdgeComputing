#!/usr/bin/env python3
"""
Merge Camera/Cabin/Station E2E logs by msg_id and compute actual end-to-end latency.

Expected log lines:
  [E2E_LOG][CAMERA] ...
  [E2E_LOG][CABIN] ...
  [E2E_LOG][STATION] ...
"""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path


def parse_kv_tokens(line: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in line.strip().split():
        if "=" not in token:
            continue
        k, v = token.split("=", 1)
        out[k] = v
    return out


def parse_log_file(path: Path) -> dict[str, dict[str, int]]:
    merged: dict[str, dict[str, int]] = {}
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "[E2E_LOG]" not in line or "msg_id=" not in line:
                continue
            fields = parse_kv_tokens(line)
            msg_id = fields.get("msg_id")
            if not msg_id:
                continue
            entry = merged.setdefault(msg_id, {})
            for k, v in fields.items():
                if k == "msg_id":
                    continue
                try:
                    entry[k] = int(v)
                except ValueError:
                    continue
    return merged


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sv = sorted(values)
    idx = max(0, min(int(round((p / 100.0) * (len(sv) - 1))), len(sv) - 1))
    return float(sv[idx])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute actual cross-device E2E latency by merging logs on msg_id.",
    )
    parser.add_argument("--camera-log", required=True, help="Camera log file path.")
    parser.add_argument("--cabin-log", required=False, help="Cabin log file path.")
    parser.add_argument("--station-log", required=True, help="Station log file path.")
    args = parser.parse_args()

    merged: dict[str, dict[str, int]] = {}
    for source in (args.camera_log, args.cabin_log, args.station_log):
        if not source:
            continue
        data = parse_log_file(Path(source).resolve())
        for msg_id, fields in data.items():
            merged.setdefault(msg_id, {}).update(fields)

    e2e_camera_to_dashboard_ms: list[float] = []
    e2e_cabin_to_dashboard_ms: list[float] = []
    for fields in merged.values():
        cam_start = fields.get("cam_capture_start_ns")
        station_done = fields.get("station_dashboard_done_ns")
        cabin_poll_done = fields.get("cabin_ultra_poll_done_ns")

        if cam_start is not None and station_done is not None and station_done >= cam_start:
            e2e_camera_to_dashboard_ms.append((station_done - cam_start) / 1_000_000.0)
        if cabin_poll_done is not None and station_done is not None and station_done >= cabin_poll_done:
            e2e_cabin_to_dashboard_ms.append((station_done - cabin_poll_done) / 1_000_000.0)

    print("Actual End-to-End Parser Summary")
    print("=" * 60)
    print(f"Merged msg_ids: {len(merged)}")

    if e2e_camera_to_dashboard_ms:
        mean_ms = statistics.mean(e2e_camera_to_dashboard_ms)
        p99_ms = percentile(e2e_camera_to_dashboard_ms, 99)
        print(f"Camera→Dashboard E2E mean/p99: {mean_ms:.1f} / {p99_ms:.1f} ms")
    else:
        print("Camera→Dashboard E2E: no complete pairs found")

    if e2e_cabin_to_dashboard_ms:
        mean_ms = statistics.mean(e2e_cabin_to_dashboard_ms)
        p99_ms = percentile(e2e_cabin_to_dashboard_ms, 99)
        print(f"Cabin sensor→Dashboard E2E mean/p99: {mean_ms:.1f} / {p99_ms:.1f} ms")
    else:
        print("Cabin sensor→Dashboard E2E: no complete pairs found")

    print()
    print("Formulae used:")
    print("  camera->dashboard: (station_dashboard_done_ns - cam_capture_start_ns) / 1e6")
    print("  cabin->dashboard:  (station_dashboard_done_ns - cabin_ultra_poll_done_ns) / 1e6")
    print("Note: cross-host subtraction assumes clock sync (chrony/NTP) and uses epoch ns.")


if __name__ == "__main__":
    main()
