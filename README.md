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
