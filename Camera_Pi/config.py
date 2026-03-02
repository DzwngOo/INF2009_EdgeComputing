# config.py
import os

##### CAMERA PI #####
# Model
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# MODEL = os.path.join(PROJECT_ROOT, "yolo26n.pt")
MODEL = os.path.join(PROJECT_ROOT, "yolo26n_ncnn_model") # applied quantization on backend
DEVICE = "cpu"           # Pi default
# Input
SOURCE = 0               # webcam index (e.g., /dev/video2)
IMGSZ = 416              # 320/416 for better FPS on Pi
CONF = 0.25
# Performance
MAX_FPS = 10.0           # 0.0 = no throttle

##### MQTT #####
BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
TOPIC = "mrt/cabin1/vision"
