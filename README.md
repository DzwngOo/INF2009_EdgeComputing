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
