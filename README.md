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
