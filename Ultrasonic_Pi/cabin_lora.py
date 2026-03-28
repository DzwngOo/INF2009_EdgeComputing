import time, serial, queue, sqlite3, uuid, os
from ultrasonic import SonarSensor
from mqtt import MqttSubscriberThread

# This file represents your "Main Application Logic"
# It runs on the main thread and imports the sensor driver

# =========================
# CONFIG
# =========================
DB_PATH = os.path.join(os.path.dirname(__file__), "lora_cache.db")
TX_INTERVAL_SECONDS = 20
RETRY_BATCH_SIZE = 10

# ADDED: camera/broker health handling
CAMERA_STALE_SECONDS = 5.0
PRIMARY_CAMERA_ID = "cam1"   # CHANGE THIS if your main camera ID is different


# =========================
# SQLite helper functions
# =========================
def init_db():
    """Create local SQLite cache for pending LoRa messages."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pending_messages (
            msg_id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            payload TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def cache_message(msg_id, payload):
    """Store outgoing message before trying to send it."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO pending_messages (msg_id, created_at, payload)
        VALUES (?, ?, ?)
    """, (msg_id, time.time(), payload))
    conn.commit()
    conn.close()
# def cache_message(msg_id, payload):
#     """Keep only the latest pending message."""
#     conn = sqlite3.connect(DB_PATH)
#     cur = conn.cursor()

#     # delete all older pending messages first
#     cur.execute("DELETE FROM pending_messages")

#     # insert only the newest message
#     cur.execute("""
#         INSERT INTO pending_messages (msg_id, created_at, payload)
#         VALUES (?, ?, ?)
#     """, (msg_id, time.time(), payload))

#     conn.commit()
#     conn.close()

def get_pending_messages(limit=RETRY_BATCH_SIZE):
    """Read oldest unsent messages first (FIFO retransmission)."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT msg_id, payload
        FROM pending_messages
        ORDER BY created_at ASC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_cached_message(msg_id):
    """Remove message from cache only after successful send."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM pending_messages WHERE msg_id = ?", (msg_id,))
    conn.commit()
    conn.close()


def count_pending_messages():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM pending_messages")
    count = cur.fetchone()[0]
    conn.close()
    return count


# =========================
# LoRa connection helpers
# =========================
def connect_lora():
    """Try to connect to LoRa module on common serial ports."""
    try:
        port_candidates = ['/dev/ttyACM0', '/dev/ttyUSB0', '/dev/ttyACM1', '/dev/ttyUSB1']
        for port in port_candidates:
            try:
                ser = serial.Serial(port, 115200, timeout=1)
                print(f"[SYSTEM] Connected to LoRa module on {port}")
                return ser
            except serial.SerialException:
                pass

        print("[WARNING] No LoRa module found on standard ports. Running in Simulation Mode.")
        return None

    except Exception as e:
        print(f"[ERROR] Serial setup failed: {e}")
        return None


def try_send_lora(lora_serial, payload):
    """Try writing one payload to LoRa serial link."""
    if not lora_serial:
        return False

    try:
        lora_serial.write((payload + '\n').encode('utf-8'))
        lora_serial.flush()
        return True
    except Exception as e:
        print(f"   [ERROR] LoRa Write Failed: {e}")
        return False


def flush_cached_messages(lora_serial):
    """
    Retry oldest cached messages first.
    Stops immediately on first failure to preserve FIFO order.
    """
    if not lora_serial:
        return False

    pending_rows = get_pending_messages(RETRY_BATCH_SIZE)
    if not pending_rows:
        return True

    print(f"[RETRY] Found {len(pending_rows)} cached message(s) in SQLite.")

    for cached_msg_id, cached_payload in pending_rows:
        ok = try_send_lora(lora_serial, cached_payload)
        if ok:
            delete_cached_message(cached_msg_id)
            print(f"   [RETRY OK] Sent cached message {cached_msg_id}")
        else:
            print(f"   [RETRY STOP] Cached message {cached_msg_id} still cannot be sent.")
            return False

    return True


# =========================
# ADDED: camera state helpers
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


# =========================
# ADDED: formatting helper
# =========================
def fmt_float(value):
    if value is None:
        return "-1"
    try:
        if float(value) < 0:
            return "-1"
        return f"{float(value):.3f}"
    except Exception:
        return "-1"


def main(train_id="T01"):
    # Initialize the sensor (starts its own background thread)
    sensor = SonarSensor()

    # NEW: moved serial setup into helper so reconnect remains easy
    lora_serial = connect_lora()

    # Create a Queue to hold the data from MQTT
    mqtt_queue = queue.Queue()

    # ADDED: keep latest state for each camera Pi
    camera_states = {}

    # initialize SQLite cache
    init_db()

    try:
        sensor.start()
        print(f"Main System Started for {train_id}. Sensor runs in background.")
        print(f"[SYSTEM] SQLite cache ready. Pending messages: {count_pending_messages()}")

        # Start MQTT Subscriber in a separate thread
        mqtt_thread = MqttSubscriberThread(mqtt_queue)
        mqtt_thread.start()

        while True:
            # try reconnecting if LoRa is currently unavailable
            if (not lora_serial) or (hasattr(lora_serial, "is_open") and not lora_serial.is_open):
                lora_serial = connect_lora()

            # if LoRa link is back, resend cached messages first
            if lora_serial:
                retry_ok = flush_cached_messages(lora_serial)
                if not retry_ok:
                    try:
                        lora_serial.close()
                    except Exception:
                        pass
                    lora_serial = None

            # ADDED: update per-camera states from MQTT
            drain_camera_queue(mqtt_queue, camera_states)

            # --- sensor health snapshot ---
            sonar_ok = 1 if sensor.is_healthy() else 0
            sonar_status = sensor.get_health_status()

            # OLD:
            # seat_status = sensor.get_latest_status()
            # distance = sensor.get_latest_distance()
            #
            # NEW: if sonar is unhealthy, do not trust its seat result
            seat_status = sensor.get_latest_status() if sonar_ok else -1
            distance = sensor.get_latest_distance()

            # --- camera health snapshot ---
            cam_state = get_effective_camera_state(camera_states, PRIMARY_CAMERA_ID, CAMERA_STALE_SECONDS)
            cam_ok = cam_state["cam_ok"]
            cam_status = cam_state["cam_status"]
            cam_data = cam_state["data"]
            cam_id = PRIMARY_CAMERA_ID

            # create unique ID for SQLite cache tracking
            msg_id = str(uuid.uuid4())[:8]

            print("=" * 10)
            print(f"[CAMERA STATES] {summarize_camera_states(camera_states)}")
            print(f"[SONAR] ok={sonar_ok} status={sonar_status} distance={distance:.2f}cm" if distance >= 0 else f"[SONAR] ok={sonar_ok} status={sonar_status} distance=INVALID")
            print(f"[PRIMARY CAMERA] id={cam_id} ok={cam_ok} status={cam_status}")

            # =========================
            # OLD:
            # if latest MQTT exists, always use it with sonar
            # else fallback to sonar-only short packet
            #
            # NEW:
            # Explicit degraded-mode logic:
            # - FUSED      : sonar ok + camera ok
            # - SONAR_ONLY : sonar ok + camera fail
            # - CAM_ONLY   : sonar fail + camera ok
            # - NO_SENSOR  : both fail
            # =========================

            capacity = -1
            confidence_avg = -1
            occupancy_ratio = -1
            cabin_status = "UNKNOWN"
            seat1_cam = -1
            final_seat1_status = "UNKNOWN"
            mode = "NO_SENSOR"

            if sonar_ok == 1 and cam_ok == 1:
                # FUSED MODE
                seat1_status = bool(cam_data["roi_presence"]["seat1"])
                seat1_cam = 1 if seat1_status else 0

                capacity = cam_data.get("capacity", -1)
                confidence_avg = cam_data.get("confidence_avg", -1)
                occupancy_ratio = cam_data.get("occupancy_ratio", -1)
                cabin_status = cam_data.get("cabin_status", "UNKNOWN")

                if seat_status == 0:
                    final_seat1_status = "EMPTY"
                else:
                    if seat1_status:
                        final_seat1_status = "TAKEN"
                    else:
                        final_seat1_status = "OBJECT"

                mode = "FUSED"

            elif sonar_ok == 1 and cam_ok == 0:
                # SONAR ONLY MODE
                # camera failed => still use sonar seat result
                # crowd density unavailable because camera failed
                final_seat1_status = "TAKEN" if seat_status == 1 else "EMPTY"
                mode = "SONAR_ONLY"

            elif sonar_ok == 0 and cam_ok == 1:
                # CAM ONLY MODE
                # ultrasonic failed => fallback to camera ROI seat result
                seat1_status = bool(cam_data["roi_presence"]["seat1"])
                seat1_cam = 1 if seat1_status else 0

                capacity = cam_data.get("capacity", -1)
                confidence_avg = cam_data.get("confidence_avg", -1)
                occupancy_ratio = cam_data.get("occupancy_ratio", -1)
                cabin_status = cam_data.get("cabin_status", "UNKNOWN")

                final_seat1_status = "TAKEN" if seat1_status else "EMPTY"
                mode = "CAM_ONLY"

            else:
                # NO SENSOR MODE
                final_seat1_status = "UNKNOWN"
                mode = "NO_SENSOR"

            # OLD:
            # msg = f"ID:{train_id}|S:{seat_status}|MSGID:{msg_id}"
            #
            # NEW:
            # packet now tells Station Pi:
            # - whether sonar failed
            # - whether primary camera failed
            # - which mode is active
            # - when no camera => crowd density fields remain unavailable
            msg = (
                f"ID:{train_id}"
                f"|S:{seat_status}"
                f"|SONAR_OK:{sonar_ok}"
                f"|SONAR_STATUS:{sonar_status}"
                f"|CAM_ID:{cam_id}"
                f"|CAM_OK:{cam_ok}"
                f"|CAM_STATUS:{cam_status}"
                f"|MODE:{mode}"
                f"|CAP:{capacity}"
                f"|CONF:{fmt_float(confidence_avg)}"
                f"|OCC:{fmt_float(occupancy_ratio)}"
                f"|CAB:{cabin_status}"
                f"|SEAT1_CAM:{seat1_cam}"
                f"|SEAT1_FINAL:{final_seat1_status}"
                f"|MSGID:{msg_id}"
            )

            print(f"\n[{TX_INTERVAL_SECONDS}s Cycle] Transmitting to Station: {msg}")
            print(f"   L Final Mode: {mode}")
            print(f"   L Final Seat 1 Status: {final_seat1_status}")
            print("=" * 10)

            # cache first in SQLite
            cache_message(msg_id, msg)
            print(f"   [CACHE] Stored message {msg_id} in SQLite. Pending now: {count_pending_messages()}")

            if lora_serial:
                ok = try_send_lora(lora_serial, msg)
                if ok:
                    delete_cached_message(msg_id)
                    print(f"   [SEND OK] Message {msg_id} sent and removed from SQLite cache.")
                else:
                    print(f"   [SEND FAIL] Message {msg_id} kept in SQLite cache for retry.")
                    try:
                        lora_serial.close()
                    except Exception:
                        pass
                    lora_serial = None
            else:
                print(f"   [CACHE ONLY] No LoRa connection. Message {msg_id} kept in SQLite cache.")

            time.sleep(TX_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\nStopping Main System...")
    finally:
        sensor.stop()
        if lora_serial:
            try:
                lora_serial.close()
            except Exception:
                pass


if __name__ == '__main__':
    main(train_id="T01")