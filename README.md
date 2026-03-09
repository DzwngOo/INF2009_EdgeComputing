# INF2009_EdgeComputing

## Camera Pi Setup

Run the following commands on the Camera Raspberry Pi:

```bash
git clone <url_gitrepo>
cd INF2009_EdgeComputing
sudo apt update && sudo apt upgrade -y
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install ultralytics ncnn
cd Camera_Pi
python3 main.py
```

## Model Comparison Setup

After Entering 'model_testing' folder, run:

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
