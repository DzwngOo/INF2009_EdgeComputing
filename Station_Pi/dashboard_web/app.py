import threading
from flask import Flask, render_template, jsonify

class DashboardState:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {
            "active_train": None,
            "ultrasonic_status": "UNKNOWN",
            "capacity": None,
            "confidence_avg": None,
            "occupancy_ratio": None,
            "cabin_status": None,
            "seat1_cam": "UNKNOWN",
            "seat1_final": None
        }

    def update(self, **kwargs):
        with self.lock:
            self.data.update(kwargs)

    def snapshot(self):
        with self.lock:
            return dict(self.data)
        
def create_flask_app(dashboard_state):
    app = Flask(__name__)

    @app.route("/")
    def dashboard():
        data = dashboard_state.snapshot()
        return render_template("index.html", data=data)

    @app.route("/api/data")
    def api_data():
        return jsonify(dashboard_state.snapshot())

    return app

def flask_thread(app):
    print("[SYSTEM] Flask dashboard starting on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
