# INF2009_EdgeComputing

## Camera Pi Setup

Run the following commands on the Raspberry Pi:

```bash
sudo apt update && sudo apt upgrade -y
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install ultralytics ncnn
