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
To download the YOLOv11s into your project folder, use the following command:

```bash
yolo export model=yolov11s.pt format=ncnn half=True imgsz=320
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

## 2.3 Testing reconnection and SQLite cache fallback

- `test_network_resilience.sh` tests the **MQTT network path** (tc-netem delay/loss on broker link). It is useful for Camera↔Broker resilience, but it does **not** directly test Cabin LoRa serial disconnection.
- For Camera USB unplug/replug tests, watch Camera Pi logs for:
  - `[CAMERA] Video source unavailable. Waiting for reconnection...`
  - `[CAMERA] Video source reconnected. Resuming inference.`
- To test Cabin SQLite store-and-forward specifically:
  1. Start Cabin Pi (`Ultrasonic_Pi/cabin_lora.py`) and Station receiver.
  2. Simulate LoRa outage by unplugging the Cabin LoRa USB serial (or disabling the serial device).
  3. Confirm Cabin logs show `[CACHE] Stored packet locally ...` and that `Ultrasonic_Pi/telemetry_cache.db` grows.
  4. Reconnect LoRa USB serial.
  5. Confirm Cabin logs show `[CACHE] Replayed <N> cached telemetry packets.` and Station starts receiving the backlog + fresh packets.


# 3. Measurement Plan

The following tools implement the five metrics described in the project measurement plan.

### 3.1 Actual cross-device E2E

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

## 3.2 Runtime capping strategy (what is enforced at runtime)

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

## 3.3 Fallback and failure behavior matrix

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
- Camera Pi reconnect visibility:
  - `Camera_Pi/mqtt_worker.py` now logs MQTT connection state transitions (`Connected`, `Connection lost`, reconnect attempts) so reconnection is visible on Camera Pi logs, not only on Station dashboard.
- Station Pi failure:
  - Current behavior is best-effort send from Cabin; if Station is down, packets are not durably buffered for later replay in this Python path.
  - For guaranteed replay, add explicit durable store-and-forward (not currently implemented).
