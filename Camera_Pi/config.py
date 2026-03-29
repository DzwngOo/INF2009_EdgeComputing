# config.py
import os
from pathlib import Path
import numpy as np

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

##### CAMERA PI #####
# Model
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
#MODEL = os.path.join(PROJECT_ROOT, "yolo26n.pt")
MODEL = str(PROJECT_DIR / "yolo11s_ncnn_model") # applied quantization on backend
DEVICE = "cpu"           # Pi default
# Input
SOURCE = 0               # webcam index (e.g., /dev/video2)
IMGSZ = 320              # 320/416 for better FPS on Pi
CONF = 0.25
# Performance
MAX_FPS = 10.0           # 0.0 = no throttle
# ROI Size
ROIS = {
    "seat1": np.array([
        [170, 290],
        [340, 290],
        [340, 520],
        [170, 520]
    ], dtype=np.int32),

    "seat2": np.array([
        [360, 290],
        [530, 290],
        [530, 520],
        [360, 520]
    ], dtype=np.int32)
}

# ROIS = {
#     "seat1": np.array([
#         [170, 260],
#         [300, 260],
#         [300, 430],
#         [170, 430]
#     ], dtype=np.int32),

#     "seat2": np.array([
#         [340, 260],
#         [470, 260],
#         [470, 430],
#         [340, 430]
#     ], dtype=np.int32)
# }

##### MQTT #####
BROKER_HOST = "172.20.10.2"
BROKER_PORT = 1884
TOPIC = "mrt/cabin1/vision"
