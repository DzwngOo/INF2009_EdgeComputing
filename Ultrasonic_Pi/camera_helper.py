import queue, time

CAMERA_STALE_SECONDS = 5.0
# =========================
# Camera state helpers
# =========================
def drain_camera_queue(mqtt_queue, camera_states):
    """
    Pull all pending MQTT messages and store latest state per camera_id.
    camera_states structure:
    {
        "cam1": {
            "data": {...},
            "last_ts": 1712345678.12
        }
    }
    """
    updated = 0

    while not mqtt_queue.empty():
        try:
            data = mqtt_queue.get_nowait()
        except queue.Empty:
            break

        camera_id = data.get("camera_id", "unknown_cam")
        camera_states[camera_id] = {
            "data": data,
            "last_ts": time.time()
        }
        updated += 1

    return updated

def get_effective_camera_state(camera_states, camera_id, stale_seconds=CAMERA_STALE_SECONDS):
    """
    Returns effective camera health after considering explicit cam_ok and staleness timeout.
    """
    entry = camera_states.get(camera_id)
    if not entry:
        return {
            "exists": False,
            "cam_ok": 0,
            "cam_status": "NO_DATA",
            "data": None,
            "age": None
        }

    data = entry["data"]
    age = time.time() - entry["last_ts"]

    payload_cam_ok = int(data.get("cam_ok", 0))
    payload_cam_status = data.get("cam_status", "UNKNOWN")

    # explicit camera failure message from Camera Pi
    if payload_cam_ok == 0:
        return {
            "exists": True,
            "cam_ok": 0,
            "cam_status": payload_cam_status,
            "data": data,
            "age": age
        }

    # stale timeout fallback if camera went silent
    if age > stale_seconds:
        return {
            "exists": True,
            "cam_ok": 0,
            "cam_status": "STALE_TIMEOUT",
            "data": data,
            "age": age
        }

    return {
        "exists": True,
        "cam_ok": 1,
        "cam_status": "OK",
        "data": data,
        "age": age
    }


def summarize_camera_states(camera_states, stale_seconds=CAMERA_STALE_SECONDS):
    """
    For broker console logging so you can see which camera Pi is broken.
    """
    if not camera_states:
        return "no camera data"

    parts = []
    for camera_id in sorted(camera_states.keys()):
        state = get_effective_camera_state(camera_states, camera_id, stale_seconds)
        parts.append(f"{camera_id}={state['cam_status']}")
    return ", ".join(parts)