from ultralytics import YOLO
import config

model = YOLO(config.MODEL)
print(model.names)          # dict like {0:'person', 1:'bicycle', ...}
print(len(model.names))     # usually 80 for COCO