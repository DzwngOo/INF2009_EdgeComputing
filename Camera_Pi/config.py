# config.py

# Model
MODEL = "yolo26n.pt"     # always YOLO26 nano
DEVICE = "cpu"           # Pi default

# Input
SOURCE = 0               # webcam index (e.g., /dev/video2)
IMGSZ = 416              # 320/416 for better FPS on Pi
CONF = 0.25

# Performance
MAX_FPS = 10.0           # 0.0 = no throttle
