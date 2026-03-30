import os
import sqlite3
import time, serial, queue

# This file represents your "Main Application Logic"
# It runs on the main thread and imports the sensor driver

CACHE_DB_PATH = os.path.join(os.path.dirname(__file__), "telemetry_cache.db")
LORA_PORT_CANDIDATES = ['/dev/ttyACM0', '/dev/ttyUSB0', '/dev/ttyACM1', '/dev/ttyUSB1']
CACHE_BURST_LIMIT = 50
TELEMETRY_CYCLE_INTERVAL_S = 5

class TelemetryCache:
    def __init__(self, db_path: str = CACHE_DB_PATH):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self.conn.commit()

    def enqueue(self, payload: str):
        self.conn.execute(
            "INSERT INTO telemetry_cache (payload, created_at) VALUES (?, ?)",
            (payload, time.time()),
        )
        self.conn.commit()

    def get_batch(self, limit: int):
        cur = self.conn.execute(
            "SELECT id, payload FROM telemetry_cache ORDER BY id ASC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()

    def ack_ids(self, ids):
        if not ids:
            return
        placeholders = ",".join(["?"] * len(ids))
        self.conn.execute(f"DELETE FROM telemetry_cache WHERE id IN ({placeholders})", ids)
        self.conn.commit()

    def size(self) -> int:
        cur = self.conn.execute("SELECT COUNT(*) FROM telemetry_cache")
        return int(cur.fetchone()[0])

    def close(self):
        self.conn.close()

def connect_lora_module():
    for port in LORA_PORT_CANDIDATES:
        try:
            lora_serial = serial.Serial(port, 115200, timeout=1)
            print(f"[SYSTEM] Connected to LoRa module on {port}")
            return lora_serial
        except serial.SerialException:
            continue
    return None

def main(train_id="T01"):
    from ultrasonic import SonarSensor
    from mqtt import MqttSubscriberThread
    # This file represents your "Main Application Logic"
    
    # Initialize the sensor (starts its own background thread)
    # sensor = SonarSensor()
    sensor1 = SonarSensor(trig_pin=23, echo_pin=24) # 1st seat
    sensor2 = SonarSensor(trig_pin=17, echo_pin=27) # 2nd seat
    
    # Initialize Serial connection to LoRa module (PlatformIO device)
    lora_serial = connect_lora_module()
    if not lora_serial:
        print("[WARNING] No LoRa module found on standard ports. Running in cache-and-retry mode.")

    # Create a Queue to hold the data from MQTT
    mqtt_queue = queue.Queue(maxsize=20)
    cache = TelemetryCache()

    try:
        sensor1.start()
        sensor2.start()
        print(f"Main System Started for {train_id}. Sensors run in background.")

        mqtt_thread = MqttSubscriberThread(mqtt_queue)
        mqtt_thread.start()

        while True:
            seat_status1 = sensor1.get_latest_status()
            distance1 = sensor1.get_latest_distance()
            sensor_health1 = sensor1.get_health_status()

            seat_status2 = sensor2.get_latest_status()
            distance2 = sensor2.get_latest_distance()
            sensor_health2 = sensor2.get_health_status()

            if sensor_health1 != "OK" and sensor_health2 != "OK":
                print("[WARNING] Both ultrasonic sensors degraded/failed. Seat status may be stale.")
            elif sensor_health1 != "OK" or sensor_health2 != "OK":
                print(
                    f"[WARNING] Ultrasonic sensor health issue: "
                    f"seat1={sensor_health1}, seat2={sensor_health2}"
                )

            status_desc1 = "TAKEN" if seat_status1 == 1 else "EMPTY"
            status_desc2 = "TAKEN" if seat_status2 == 1 else "EMPTY"

            print("=" * 10)

            message_data = None
            while not mqtt_queue.empty():
                message_data = mqtt_queue.get()

            if message_data is not None:
                print(f"   L Capacity: {message_data['capacity']}")
                print(f"   L Confidence Average: {message_data['confidence_avg']}")
                print(f"   L Occupancy Ratio: {message_data['occupancy_ratio']}")
                print(f"   L Cabin Status: {message_data['cabin_status']}")

                roi_presence = message_data.get('roi_presence', {})

                seat1_cam = roi_presence.get('seat1', 0)
                seat2_cam = roi_presence.get('seat2', 0)

                final_seat1_status = "EMPTY" if seat_status1 == 0 else ("TAKEN" if seat1_cam else "OBJECT")
                final_seat2_status = "EMPTY" if seat_status2 == 0 else ("TAKEN" if seat2_cam else "OBJECT")

                msg = (
                    f"ID:{train_id}"
                    f"|S1:{seat_status1}"
                    f"|S2:{seat_status2}"
                    f"|CAP:{message_data['capacity']}"
                    f"|CONF:{message_data['confidence_avg']:.3f}"
                    f"|OCC:{message_data['occupancy_ratio']:.3f}"
                    f"|CAB:{message_data['cabin_status']}"
                    f"|SEAT1_CAM:{int(seat1_cam)}"
                    f"|SEAT1_FINAL:{final_seat1_status}"
                    f"|SEAT2_CAM:{int(seat2_cam)}"
                    f"|SEAT2_FINAL:{final_seat2_status}"
                    f"|UH1:{sensor_health1}"
                    f"|UH2:{sensor_health2}"
                )

                msg_id = message_data.get("msg_id")
                if msg_id:
                    msg += f"|MID:{msg_id}"

                cam_capture_start_ns = message_data.get("cam_capture_start_ns")
                if cam_capture_start_ns is not None:
                    msg += f"|CAM_CAP_NS:{int(cam_capture_start_ns)}"

                cam_capture_start_perf_ns = message_data.get("cam_capture_start_perf_ns")
                if cam_capture_start_perf_ns is not None:
                    msg += f"|CAM_CAP_PNS:{int(cam_capture_start_perf_ns)}"

                cam_mqtt_publish_done_ns = message_data.get("cam_mqtt_publish_done_ns")
                if cam_mqtt_publish_done_ns is not None:
                    msg += f"|CAM_PUB_NS:{int(cam_mqtt_publish_done_ns)}"

                cam_mqtt_publish_done_perf_ns = message_data.get("cam_mqtt_publish_done_perf_ns")
                if cam_mqtt_publish_done_perf_ns is not None:
                    msg += f"|CAM_PUB_PNS:{int(cam_mqtt_publish_done_perf_ns)}"

                print(f"\n[20s Cycle] Transmitting to Station: {msg}")
                print(f"   L Seat 1 Raw Distance: {distance1:.2f}cm")
                print(f"   L Seat 1 Interpretation: {status_desc1} (<20cm is TAKEN)")
                print(f"   L Final Seat 1 Status: {final_seat1_status}")

                print(f"   L Seat 2 Raw Distance: {distance2:.2f}cm")
                print(f"   L Seat 2 Interpretation: {status_desc2} (<20cm is TAKEN)")
                print(f"   L Final Seat 2 Status: {final_seat2_status}")

            else:
                msg = (
                    f"ID:{train_id}"
                    f"|S1:{seat_status1}"
                    f"|S2:{seat_status2}"
                    f"|UH1:{sensor_health1}"
                    f"|UH2:{sensor_health2}"
                )

                print(f"\n[20s Cycle] Transmitting to Station: {msg}")
                print(f"   L Seat 1 Raw Distance: {distance1:.2f}cm")
                print(f"   L Seat 1 Interpretation: {status_desc1} (<20cm is TAKEN)")
                print(f"   L Seat 2 Raw Distance: {distance2:.2f}cm")
                print(f"   L Seat 2 Interpretation: {status_desc2} (<20cm is TAKEN)")
        # ==== Deric's ====

        # ==== XK's ====
        # while True:
        #     # --- YOUR MAIN LOGIC ---
            
        #     # 1. Pull latest data from sonar (Instant)
        #     # You can pull this anytime. The sensor updates itself ~5 times/sec in the background.
        #     seat_status = sensor.get_latest_status()
        #     distance = sensor.get_latest_distance()
            
        #     # 2. Simulate LoRa Transmission
        #     # Packet Format: "ID:T01|S:1"
        #     # The '|' acts as a delimiter so the receiver can split the string easily
        #     msg = f"ID:{train_id}|S:{seat_status}"
            
        #     status_desc = "TAKEN" if seat_status == 1 else "EMPTY"
        #     print(f"\n[20s Cycle] Transmitting to Station: {msg}")
        #     print(f"   L Raw Distance: {distance:.2f}cm")
        #     print(f"   L Interpretation: {status_desc} (<20cm is TAKEN)")
        # ==== XK's ====
            
            if lora_serial is None:
                lora_serial = connect_lora_module()

            # Send cached packets first when link is up, then current packet.
            sent_current = False
            if lora_serial:
                try:
                    flushed = 0
                    while True:
                        batch = cache.get_batch(CACHE_BURST_LIMIT)
                        if not batch:
                            break
                        sent_ids = []
                        for row_id, payload in batch:
                            lora_serial.write((payload + '\n').encode('utf-8'))
                            sent_ids.append(row_id)
                            flushed += 1
                        cache.ack_ids(sent_ids)
                    if flushed:
                        print(f"[CACHE] Replayed {flushed} cached telemetry packets.")

                    print(msg)
                    cabin_ultra_poll_done_ns = time.time_ns()
                    cabin_ultra_poll_done_perf_ns = time.perf_counter_ns()
                    lora_serial.write((msg + '\n').encode('utf-8'))
                    cabin_lora_tx_done_ns = time.time_ns()
                    cabin_lora_tx_done_perf_ns = time.perf_counter_ns()
                    sent_current = True
                    if message_data is not None and message_data.get("msg_id"):
                        print(
                            f"[E2E_LOG][CABIN] msg_id={message_data['msg_id']} "
                            f"cabin_ultra_poll_done_ns={cabin_ultra_poll_done_ns} "
                            f"cabin_ultra_poll_done_perf_ns={cabin_ultra_poll_done_perf_ns} "
                            f"cabin_lora_tx_done_ns={cabin_lora_tx_done_ns} "
                            f"cabin_lora_tx_done_perf_ns={cabin_lora_tx_done_perf_ns}"
                        )
                except Exception as e:
                    print(f"   [ERROR] LoRa Write Failed: {e}")
                    try:
                        lora_serial.close()
                    except Exception:
                        pass
                    lora_serial = None

            if not sent_current:
                cache.enqueue(msg)
                print(f"[CACHE] Stored packet locally (pending={cache.size()}).")

            time.sleep(TELEMETRY_CYCLE_INTERVAL_S)
            
    except KeyboardInterrupt:
        print("\nStopping Main System...")
    finally:
        # Always clean up the sensor thread on exit
        sensor1.stop()
        sensor2.stop()
        if lora_serial:
            lora_serial.close()
        cache.close()

if __name__ == '__main__':
    # You can change this ID for different trains (e.g. T02, T03)
    main(train_id="T01")
