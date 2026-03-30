import time, serial, threading, sys
from dashboard_web.app import DashboardState, create_flask_app, flask_thread

# Cabin transmits every ~20s; classify one missed cycle as degraded and
# three missed cycles as offline for dashboard operator visibility.
CABIN_LINK_DEGRADED_S = 30
CABIN_LINK_OFFLINE_S = 60

class StationReceiver:
    def __init__(self, dashboard_state):
        self.active_train = None
        self.seat_status1 = None
        self.seat_status2 = None
        self.dashboard_state = dashboard_state
        self.last_packet_time = None

    def handle_arrival(self, train_id):
        """Simulate a train arriving and locking onto its signal."""
        print(f"\n[EVENT] Train {train_id} has arrived at the platform.")
        print(f"[SYSTEM] Creating secure link to {train_id}...")
        self.active_train = train_id
        self.seat_status1 = None
        self.seat_status2 = None

        self.dashboard_state.update(
            active_train=train_id,
            ultrasonic_status1="UNKNOWN",
            ultrasonic_status2="UNKNOWN",
            capacity=None,
            confidence_avg=None,
            occupancy_ratio=None,
            cabin_status=None,
            seat1_cam="UNKNOWN",
            seat1_final=None,
            seat2_cam="UNKNOWN",
            seat2_final=None,
            camera_status="UNKNOWN",
            ultrasonic_health1="UNKNOWN",
            ultrasonic_health2="UNKNOWN",
            cabin_link_status="WAITING"
        )

    def handle_departure(self):
        """Simulate the train leaving."""
        if self.active_train:
            print(f"\n[EVENT] Train {self.active_train} has departed.")
            print("[SYSTEM] Closing link. Returning to IDLE mode.")
            self.active_train = None
            self.seat_status1 = None
            self.seat_status2 = None

            self.dashboard_state.update(
                active_train=None,
                ultrasonic_status1="UNKNOWN",
                ultrasonic_status2="UNKNOWN",
                capacity=None,
                confidence_avg=None,
                occupancy_ratio=None,
                cabin_status=None,
                seat1_cam="UNKNOWN",
                seat1_final=None,
                seat2_cam="UNKNOWN",
                seat2_final=None,
                camera_status="UNKNOWN",
                ultrasonic_health1="UNKNOWN",
                ultrasonic_health2="UNKNOWN",
                cabin_link_status="INACTIVE"
            )
        else:
            print("[ERROR] No train is currently at the platform.")

    def process_lora_packet(self, raw_data):
        """
        Parses incoming LoRa data.

        Full format:
        ID:T01|S1:1|S2:0|CAP:40|CONF:0.800|OCC:0.250|CAB:LOW|SEAT1_CAM:1|SEAT1_FINAL:TAKEN|SEAT2_CAM:0|SEAT2_FINAL:EMPTY

        Ultrasonic-only fallback format:
        ID:T01|S1:1|S2:0|UH1:OK|UH2:OK
        """
        station_lora_rx_ns = time.time_ns()
        station_lora_rx_perf_ns = time.perf_counter_ns()
        raw_data = raw_data.strip()
        print(raw_data)

        if not self.active_train:
            return

        try:
            fields = {}
            for part in raw_data.split('|'):
                if ':' not in part:
                    continue
                key, value = part.split(':', 1)
                fields[key.strip()] = value.strip()

            # Required fields
            received_id = fields['ID']
            received_status1 = int(fields['S1'])
            received_status2 = int(fields['S2'])

            ultrasonic_text1 = "TAKEN" if received_status1 == 1 else "EMPTY"
            ultrasonic_text2 = "TAKEN" if received_status2 == 1 else "EMPTY"

            ultrasonic_health1 = fields.get('UH1', "UNKNOWN")
            ultrasonic_health2 = fields.get('UH2', "UNKNOWN")

            msg_id = fields.get('MID')
            cam_capture_start_ns = int(fields['CAM_CAP_NS']) if 'CAM_CAP_NS' in fields else None
            cam_capture_start_perf_ns = int(fields['CAM_CAP_PNS']) if 'CAM_CAP_PNS' in fields else None
            cam_publish_done_ns = int(fields['CAM_PUB_NS']) if 'CAM_PUB_NS' in fields else None
            cam_publish_done_perf_ns = int(fields['CAM_PUB_PNS']) if 'CAM_PUB_PNS' in fields else None

            # Detect whether any camera-side data exists
            camera_payload_present = any(
                key in fields for key in (
                    'CAP', 'CONF', 'OCC', 'CAB',
                    'SEAT1_CAM', 'SEAT1_FINAL',
                    'SEAT2_CAM', 'SEAT2_FINAL'
                )
            )

            # Optional camera/cabin fields
            capacity = int(fields['CAP']) if 'CAP' in fields else None
            confidence_avg = float(fields['CONF']) if 'CONF' in fields else None
            occupancy_ratio = float(fields['OCC']) if 'OCC' in fields else None
            cabin_status = fields.get('CAB')

            seat1_cam = int(fields['SEAT1_CAM']) if 'SEAT1_CAM' in fields else None
            seat2_cam = int(fields['SEAT2_CAM']) if 'SEAT2_CAM' in fields else None

            # Fallback logic:
            # if camera is down and SEAT*_FINAL is missing, use ultrasonic status
            seat1_final = fields.get('SEAT1_FINAL', ultrasonic_text1)
            seat2_final = fields.get('SEAT2_FINAL', ultrasonic_text2)

            seat1_cam_text = "UNKNOWN" if seat1_cam is None else ("TAKEN" if seat1_cam == 1 else "EMPTY")
            seat2_cam_text = "UNKNOWN" if seat2_cam is None else ("TAKEN" if seat2_cam == 1 else "EMPTY")

            camera_status = "ONLINE" if camera_payload_present else "OFFLINE"

            if not camera_payload_present:
                print("[MODE] Ultrasonic-only fallback packet received (camera offline).")

            print(f"\n[PARSED DATA]")
            print(f"   L Train ID: {received_id}")
            print(f"   L Ultrasonic Seat 1: {ultrasonic_text1}")
            print(f"   L Ultrasonic Seat 2: {ultrasonic_text2}")
            print(f"   L Ultrasonic Health 1: {ultrasonic_health1}")
            print(f"   L Ultrasonic Health 2: {ultrasonic_health2}")

            if capacity is not None:
                print(f"   L Capacity: {capacity}")
            if confidence_avg is not None:
                print(f"   L Confidence Average: {confidence_avg:.3f}")
            if occupancy_ratio is not None:
                print(f"   L Occupancy Ratio: {occupancy_ratio:.3f}")
            if cabin_status is not None:
                print(f"   L Cabin Status: {cabin_status}")

            print(f"   L Camera Seat 1: {seat1_cam_text}")
            print(f"   L Final Seat 1: {seat1_final}")
            print(f"   L Camera Seat 2: {seat2_cam_text}")
            print(f"   L Final Seat 2: {seat2_final}")
            print(f"   L Camera Status: {camera_status}")

            if received_id == self.active_train:
                self.seat_status1 = received_status1
                self.seat_status2 = received_status2

                self.dashboard_state.update(
                    active_train=received_id,
                    ultrasonic_status1=ultrasonic_text1,
                    ultrasonic_status2=ultrasonic_text2,
                    capacity=capacity,
                    confidence_avg=confidence_avg,
                    occupancy_ratio=occupancy_ratio,
                    cabin_status=cabin_status,
                    seat1_cam=seat1_cam_text,
                    seat1_final=seat1_final,
                    seat2_cam=seat2_cam_text,
                    seat2_final=seat2_final,
                    camera_status=camera_status,
                    ultrasonic_health1=ultrasonic_health1,
                    ultrasonic_health2=ultrasonic_health2,
                    cabin_link_status="ONLINE"
                )
                self.last_packet_time = time.time()

                station_dashboard_done_ns = time.time_ns()
                station_dashboard_done_perf_ns = time.perf_counter_ns()
                if msg_id:
                    print(
                        f"[E2E_LOG][STATION] msg_id={msg_id} "
                        f"station_lora_rx_ns={station_lora_rx_ns} "
                        f"station_lora_rx_perf_ns={station_lora_rx_perf_ns} "
                        f"station_dashboard_done_ns={station_dashboard_done_ns} "
                        f"station_dashboard_done_perf_ns={station_dashboard_done_perf_ns} "
                        f"cam_capture_start_ns={cam_capture_start_ns if cam_capture_start_ns is not None else -1} "
                        f"cam_capture_start_perf_ns={cam_capture_start_perf_ns if cam_capture_start_perf_ns is not None else -1} "
                        f"cam_mqtt_publish_done_ns={cam_publish_done_ns if cam_publish_done_ns is not None else -1} "
                        f"cam_mqtt_publish_done_perf_ns={cam_publish_done_perf_ns if cam_publish_done_perf_ns is not None else -1}"
                    )
            else:
                print(f"[IGNORE] Packet train ID {received_id} does not match active train {self.active_train}")

        except (IndexError, ValueError, KeyError) as e:
            if "Heartbeat" in raw_data or "Ping" in raw_data or "CRC" in raw_data:
                pass
            else:
                print(f"[ERROR] Malformed packet received: {raw_data}")
                print(f"[ERROR] Parse details: {e}")

    def refresh_link_health(self):
        if not self.active_train:
            return
        now = time.time()
        if self.last_packet_time is None:
            self.dashboard_state.update(cabin_link_status="WAITING")
            return
        lag = now - self.last_packet_time
        if lag > CABIN_LINK_OFFLINE_S:
            status = "OFFLINE"
        elif lag > CABIN_LINK_DEGRADED_S:
            status = "DEGRADED"
        else:
            status = "ONLINE"
        self.dashboard_state.update(cabin_link_status=status)

def serial_listener(station, port_name):
    """Background thread to listen to real LoRa hardware"""
    try:
        ser = serial.Serial(port_name, 115200, timeout=1)
        print(f"[SYSTEM] Connected to LoRa Hardware on {port_name}")
        while True:
            if ser.in_waiting:
                try:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    print(f"[RAW] {repr(line)}")

                    if "[RX] Data: " in line:
                        parts = line.split("[RX] Data: ")
                        if len(parts) > 1:
                            payload_section = parts[1]
                            payload = payload_section.split(" | ")[0]
                            station.process_lora_packet(payload)

                    elif line.startswith("ID:") and "|S1:" in line and "|S2:" in line:
                        station.process_lora_packet(line)

                except Exception as e:
                    print(f"[SERIAL ERROR] {e}")
            time.sleep(0.1)
    except serial.SerialException:
        print(f"[WARNING] Could not open {port_name}. Running in Simulation-Only mode.")


def link_health_watchdog(station):
    while True:
        station.refresh_link_health()
        time.sleep(1.0)


def main():
    dashboard_state = DashboardState()
    station = StationReceiver(dashboard_state)

    app = create_flask_app(dashboard_state)
    web_thread = threading.Thread(target=flask_thread, args=(app,), daemon=True)
    web_thread.start()

    port_candidates = ['/dev/ttyACM0', '/dev/ttyUSB0', 'COM3', 'COM4']

    selected_port = None
    for port in port_candidates:
        try:
            s = serial.Serial(port)
            s.close()
            selected_port = port
            break
        except:
            pass

    if selected_port:
        t = threading.Thread(target=serial_listener, args=(station, selected_port), daemon=True)
        t.start()
    else:
        print("[WARNING] No Serial Port found. Input commands manually.")

    t_health = threading.Thread(target=link_health_watchdog, args=(station,), daemon=True)
    t_health.start()

    print("--- STATION PI DASHBOARD SIMULATOR ---")
    print("Commands:")
    print("  ARRIVE <ID>  -> Simulate train arrival")
    print("  DEPART       -> Simulate train departure")
    print("  DATA <MSG>   -> Simulate receiving LoRa packet")
    print("  EXIT         -> Quit")
    print("----------------------------------------")

    try:
        while True:
            user_input = input("\nStation_Pi > ").strip().upper()

            if user_input.startswith("ARRIVE"):
                parts = user_input.split()
                if len(parts) > 1:
                    train_id = parts[1]
                    station.handle_arrival(train_id)
                else:
                    print("[ERROR] Usage: ARRIVE <TrainID>")

            elif user_input == "DEPART":
                station.handle_departure()

            elif user_input.startswith("DATA"):
                if len(user_input) > 5:
                    raw_payload = user_input[5:]
                    station.process_lora_packet(raw_payload)
                else:
                    print("[ERROR] Usage: DATA ID:T01|S1:1|S2:0")

            elif user_input == "EXIT":
                print("Shutting down station...")
                break
            else:
                print("[ERROR] Unknown command.")

    except KeyboardInterrupt:
        print("\nShutting down station...")

if __name__ == "__main__":
    main()
