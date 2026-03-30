# INF2009_EdgeComputing

# 1. Camera Pi

## 1.1 Setup
Run the following commands to set up the Camera Pi:

```bash
git clone <url_gitrepo>             # Clone the repository
cd INF2009_EdgeComputing            # Navigate into the project folder
sudo apt update && sudo apt upgrade -y  # Update and upgrade system packages
python3 -m venv --system-site-packages venv  # Create a virtual environment
source venv/bin/activate            # Activate the virtual environment
pip install -r requirements.txt     # Install required dependencies
cd Camera_Pi                        # Navigate to the Camera Pi directory
python3 main.py                     # Start the main script for Camera Pi
```

## 1.2 Model Download
To download the YOLO26n into your project folder, use the following command:

```bash
yolo export model=yolo26n.pt format=ncnn half=True imgsz=320
```

## 1.3 Model Comparison Setup
Once you're inside the model_testing folder, use the following command to compare different models:

```bash
python3 compare_models.py \
--models baseline=../../yolo26n.pt ncnn_fp16=../../yolo26n_ncnn_model \
--source 0 \
--imgsz 320 \
--conf 0.25 \
--frames 300 \
--warmup 30 \
--summary-out summary.csv
```

# 3. Measurement Plan

The following tools implement the five metrics described in the project measurement plan.

## 3.0 Quick answer: which commands do I run, and what do they cover?

Your two commands are correct, but they do **not** cover every hardware stage:

```bash
cd Camera_Pi
python3 measure_latency.py \
    --model ../yolo11s_ncnn_model \
    --source 0 \
    --cycles 500 \
    --warmup 30 \
    --broker-host 127.0.0.1 --broker-port 1884 \
    --out latency_results.csv
```

```bash
sudo bash test_network_resilience.sh 127.0.0.1 1884 mrt/cabin1/vision
```

Coverage summary:

- `measure_latency.py`: **Camera Pi-side measurement only** (capture/preprocess, YOLO inference, MQTT publish from Camera Pi).
- `test_network_resilience.sh`: MQTT-topic resilience on the local broker path.
- Not directly measured by those two commands: Ultrasonic polling (Cabin/Ultrasonic Pi), LoRa airtime, Station Pi ingest/render path.

## 3.1 Metric 1 — End-to-end latency (target ≤ 2000 ms)

`Camera_Pi/measure_latency.py` times every measurable stage of the Camera Pi pipeline
using `time.perf_counter()`, runs the requested number of cycles (default 500),
and reports **mean ± σ** and **p99** for each stage plus the end-to-end sum.

**Pipeline stages timed:**

| Stage | Description | Expected |
|-------|-------------|----------|
| 1-2 | Frame capture + preprocess (`cap.read()` + resize) | ~15 ms |
| 3 | YOLO inference (`model.predict()`) | ~42 ms |
| 5-6 | MQTT JSON serialise + `client.publish()` | ~10 ms |

Stages 4, 7, 8-9 run on separate hardware; their expected latencies are printed for reference.

```bash
cd Camera_Pi
python3 measure_latency.py \
    --model ../yolo11s_ncnn_model \
    --source 0 \
    --imgsz 320 \
    --cycles 500 \
    --warmup 30 \
    --broker-host 127.0.0.1 \
    --broker-port 1884 \
    --out latency_results.csv
```

Results are saved to `latency_results.csv` (one row per cycle).

You can automatically parse that CSV into a single end-to-end summary:

```bash
cd Camera_Pi
python3 parse_latency_results.py --in latency_results.csv
```

This reports:
- Camera-side measured E2E (mean, p99)
- Full estimated E2E (Camera + default Stage 4/7/8-9 values)
- Budget check against 2000 ms

To override remote-stage assumptions:

```bash
python3 parse_latency_results.py \
    --in latency_results.csv \
    --stage4-ms 18 \
    --stage7-ms 460 \
    --stage8_9-ms 220 \
    --budget-ms 2000
```

**Live monitoring during normal operation:**
Per-stage latency (mean ± σ, p99) is also printed automatically every 100 frames by
`inference_worker.py` when `main.py` is running. The interval can be changed via the
`latency_report_every` parameter in `main.py`.

## 3.2 Metric 2 — Inference FPS (target ≥ 5 FPS sustained)

`measure_latency.py` includes a sustained-FPS measurement window (default 60 s).
It runs inference continuously for the specified window and reports frames-per-second.

The `--fps-window` argument controls the window length:

```bash
python3 measure_latency.py --model ../yolo11s_ncnn_model --source 0 --fps-window 60
```

Use `--skip-fps` to omit the FPS window and only run the latency cycles.

## 3.3 Metric 3 — Network resilience (recover within 3 s)

`test_network_resilience.sh` uses **tc-netem** to inject 200 ms RTT + 5 % packet loss
on the loopback interface, then measures how quickly the pipeline resumes publishing
after the impairment is removed.

**Requirements:** `iproute2`, `mosquitto-clients`, `bc` and root access.

```bash
# Install dependencies (once)
sudo apt-get install -y iproute2 mosquitto-clients bc

# Run the test (pipeline must already be running)
sudo bash test_network_resilience.sh 127.0.0.1 1884 mrt/cabin1/vision
```

The script:
1. Captures the current last-known state from the MQTT topic.
2. Applies `tc qdisc add dev lo root netem delay 100ms loss 5%` (≈ 200 ms RTT).
3. Verifies the pipeline continues publishing under impairment.
4. Removes the impairment and measures the time until fresh data arrives.
5. Reports **PASS** if recovery ≤ 3 s, **FAIL** otherwise.
6. Always restores the loopback interface on exit (even on error).

## 3.4 Measuring Station Pi + Cabin (Ultrasonic Pi) stages

To measure the **full pipeline across devices**, run all three apps together and
collect timestamps from each host (Camera Pi, Ultrasonic/Cabin Pi, Station Pi).

### 3.4.1 Recommended timing method

- Use `time.perf_counter()` / `time.perf_counter_ns()` for stage latency in Python code.
- Use `cProfile` only for CPU hotspot analysis (where time is spent), not for network/LoRa end-to-end latency.
- Use Linux `perf` only if you need low-level kernel/CPU event profiling; it is optional for this project.

### 3.4.2 Practical cross-device workflow

1. **Sync clocks** on all Pis first (NTP/chrony).
2. Run Camera Pi benchmark (`measure_latency.py`) for camera-side stages.
3. Run Cabin Pi app:
   ```bash
   cd Ultrasonic_Pi
   python3 cabin_lora.py
   ```
4. Run Station Pi app:
   ```bash
   cd Station_Pi
   python3 station_lora.py
   ```
5. Collect per-stage timestamps from console logs:
   - Cabin Pi: message build/send cycle and LoRa write timing
   - Station Pi: packet receive/parse/update timing
6. Compute:
   - Stage 4 (ultrasonic): from sensor poll timing on Cabin Pi
   - Stage 7 (LoRa): Cabin send timestamp to Station receive timestamp
   - Stages 8-9 (cloud/dashboard): Station ingest to dashboard update timestamp

The two commands above are the core automated checks, but full multi-device
latency still requires running Cabin + Station components concurrently.

### 3.4.3 Actual cross-device E2E (implemented)

Yes — you can now measure actual end-to-end automatically by propagating one
`msg_id` across Camera → Cabin → Station and parsing timestamp logs.

What is now logged:
- Camera Pi: capture start + MQTT publish done
- Cabin Pi: ultrasonic poll done + LoRa TX done
- Station Pi: LoRa RX + dashboard update done

All three apps print tagged lines:
- `[E2E_LOG][CAMERA] ...`
- `[E2E_LOG][CABIN] ...`
- `[E2E_LOG][STATION] ...`

### Final workflow (what to run)

1. Sync clocks on all 3 Pis (Camera/Cabin/Station), then verify:
   ```bash
   timedatectl status
   ```
   Ensure NTP is active before measuring.

2. On **Station Pi**, start the app with unbuffered output (so `station.log` is written immediately):
   ```bash
   cd /path/to/INF2009_EdgeComputing/Station_Pi
   python3 -u station_lora.py 2>&1 | tee station.log
   ```
   In the Station terminal, run:
   ```text
   ARRIVE T01
   ```
   (Station ignores data until a train is set as active.)

3. On **Cabin Pi**, start Cabin app with unbuffered output:
   ```bash
   cd /path/to/INF2009_EdgeComputing/Ultrasonic_Pi
   python3 -u cabin_lora.py 2>&1 | tee cabin.log
   ```
   Wait at least one 20s cycle before judging log output.

4. On **Camera Pi**, start Camera app and save logs:
   ```bash
   cd /path/to/INF2009_EdgeComputing/Camera_Pi
   python3 -u main.py 2>&1 | tee camera.log
   ```

5. Let the system run for enough samples, then stop all apps (`Ctrl+C`) so log files are complete.

6. Copy `camera.log`, `cabin.log`, `station.log` to one machine with the repo and run:

```bash
cd /path/to/INF2009_EdgeComputing
python3 parse_actual_e2e_logs.py \
    --camera-log camera.log \
    --cabin-log cabin.log \
    --station-log station.log
```

Troubleshooting (empty `cabin.log` / `station.log`):
- If log files stay empty while process is still running, make sure you used `python3 -u ... | tee ...` (unbuffered mode).
- On Station Pi, seeing only startup text is normal until data arrives; you must run `ARRIVE <TrainID>` first (example `ARRIVE T01`).
- If Station shows `[WARNING] No Serial Port found. Input commands manually.`, LoRa hardware is not connected. In that case, no real Cabin→Station packets will arrive.

Exact formulas used by the parser:
- Camera-to-dashboard:
  - `E2E_actual_ms = (station_dashboard_done_ns - cam_capture_start_ns) / 1e6`
- Cabin-sensor-to-dashboard:
  - `E2E_actual_ms = (station_dashboard_done_ns - cabin_ultra_poll_done_ns) / 1e6`

Important:
- For cross-host subtraction, the parser uses wall-clock epoch timestamps (`time.time_ns()`),
  so keep clocks synced (chrony/NTP).
- `time.perf_counter_ns()` is still logged for per-host stage analysis but should not be
  directly subtracted across machines without offset compensation.

## 3.5 Runtime capping strategy (what is enforced at runtime)

This section defines the **live runtime limits** currently enforced by code.

- Camera inference pacing:
  - `Camera_Pi/config.py` sets `MAX_FPS = 10.0`.
  - `Camera_Pi/inference_worker.py` enforces pacing using `time.perf_counter()` sleep scheduling.
  - This is the active runtime throttle for CPU load.
- Camera publish queue cap:
  - `Camera_Pi/main.py` uses `PUBLISH_Q = queue.Queue(maxsize=50)`.
  - On overflow, `inference_worker.py` drops the **oldest** item and inserts the newest result (`drop_old_on_full=True`), so memory remains bounded.
- Camera display queue cap:
  - `DISPLAY_Q = queue.Queue(maxsize=1)`.
  - If full, new debug frames are skipped (drop newest for UI path), keeping inference/publish path prioritized.
- Cabin MQTT ingest queue cap:
  - `Ultrasonic_Pi/cabin_lora.py` uses `mqtt_queue = queue.Queue(maxsize=20)`.
  - `Ultrasonic_Pi/mqtt.py` uses drop-oldest-on-full behavior to keep latest data and bound memory.
- LoRa TX backlog behavior:
  - Cabin sends one payload per 20-second cycle and flushes MQTT queue to latest value before send.
  - There is no unbounded TX backlog queue in Python cabin logic.

Current scope notes:
- There is **no hard OS-level CPU quota** (e.g. `cpulimit`/cgroup quota) enforced by this repo at runtime.
- There is **no process RSS hard memory cap** enforced by this repo at runtime.
- If required for deployment policy, apply host/container cgroup limits in systemd/Docker.

## 3.6 Fallback and failure behavior matrix

- Camera failure (disconnect / sustained no frames):
  - Inference loop exits when `cap.read()` fails.
  - Cabin continues transmitting ultrasonic status (`S1/S2`) every cycle.
  - Station marks camera as `OFFLINE` when camera-derived fields (`CAP`/`CONF`) are absent, while still showing ultrasonic data.
- Ultrasonic sensor failure:
  - Each sensor now publishes health state (`UH1`, `UH2`) as `OK`, `DEGRADED`, or `FAILED`.
  - Health is based on consecutive invalid reads; invalid-streak escalation is explicit in `Ultrasonic_Pi/ultrasonic.py`.
  - If both sensors degrade/fail, Cabin prints warning that seat status may be stale.
- Cabin Pi failure / publisher stall:
  - Station tracks last packet time and sets `cabin_link_status`:
    - `ONLINE` (fresh packets),
    - `DEGRADED` (>30 s without packet),
    - `OFFLINE` (>60 s without packet),
    - `WAITING` (train arrived but no packet yet).
- Cabin Pi LoRa disconnect fallback:
  - Cabin now writes unsent telemetry to local SQLite (`Ultrasonic_Pi/telemetry_cache.db`) when LoRa is unavailable.
  - On reconnect, Cabin replays cached packets in FIFO bursts before sending the newest packet.
  - This provides store-and-forward behavior during temporary LoRa outages.
- Station Pi failure:
  - Current behavior is best-effort send from Cabin; if Station is down, packets are not durably buffered for later replay in this Python path.
  - For guaranteed replay, add explicit durable store-and-forward (not currently implemented).

# 2. Station Pi

## 2.1 Setup
Run the following commands to set up the Station Pi:

```bash
git clone <url_gitrepo>              # Clone the repository
cd INF2009_EdgeComputing            # Navigate into the project folder
sudo apt update && sudo apt upgrade -y  # Update and upgrade system packages
python3 -m venv --system-site-packages venv  # Create a virtual environment
source venv/bin/activate            # Activate the virtual environment
pip install -r requirements.txt     # Install required dependencies
cd Ultrasonic_Pi                    # Navigate to the Station Pi directory
python3 cabin_lora.py               # Start the LoRa data collection script
```

## 2.2 MQTT
To set up MQTT on your Station Pi, follow these steps:

### 2.2.1 Start the Mosquitto service:
```bash
sudo systemctl start mosquitto     # Start Mosquitto service
sudo systemctl enable mosquitto    # Enable Mosquitto to start on boot
sudo systemctl status mosquitto    # Check Mosquitto service status
```

### 2.2.2 Configure Mosquitto:
Open the Mosquitto configuration file:
```bash
sudo nano /etc/mosquitto/mosquitto.conf
```
Add the following lines to configure the listener and allow anonymous connections:
```bash
Add this inside:
bind_address 0.0.0.0
listener 1884
allow_anonymous true
```

### 2.2.3 Restart the Mosquitto service:
```bash
sudo systemctl restart mosquitto   # Restart Mosquitto to apply changes
```
