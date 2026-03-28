import time, serial, threading, sys
from dashboard_web.app import DashboardState, create_flask_app, flask_thread

class StationReceiver:
    def __init__(self, dashboard_state):
        self.active_train = None
        self.seat_status = None  # None means unconfirmed
        self.dashboard_state = dashboard_state

    def handle_arrival(self, train_id):
        """Simulate a train arriving and locking onto its signal."""
        print(f"\n[EVENT] Train {train_id} has arrived at the platform.")
        print(f"[SYSTEM] Creating secure link to {train_id}...")
        self.active_train = train_id
        self.seat_status = None

        self.dashboard_state.update(
            active_train=train_id,
            ultrasonic_status="UNKNOWN",
            capacity=None,
            confidence_avg=None,
            occupancy_ratio=None,
            cabin_status=None,
            seat1_cam="UNKNOWN",
            seat1_final=None
        )

    def handle_departure(self):
        """Simulate the train leaving."""
        if self.active_train:
            print(f"\n[EVENT] Train {self.active_train} has departed.")
            print("[SYSTEM] Closing link. Returning to IDLE mode.")
            self.active_train = None
            self.seat_status = None

            self.dashboard_state.update(
                active_train=None,
                ultrasonic_status="UNKNOWN",
                capacity=None,
                confidence_avg=None,
                occupancy_ratio=None,
                cabin_status=None,
                seat1_cam="UNKNOWN",
                seat1_final=None
            )
        else:
            print("[ERROR] No train is currently at the platform.")

    def _safe_int_or_none(self, value):
        try:
            parsed = int(value)
            return None if parsed < 0 else parsed
        except Exception:
            return None

    def _safe_float_or_none(self, value):
        try:
            parsed = float(value)
            return None if parsed < 0 else parsed
        except Exception:
            return None

    def process_lora_packet(self, raw_data):
        """
        Parses incoming LoRa data.

        New broker packet example:
        ID:T01|S:1|SONAR_OK:1|SONAR_STATUS:OK|CAM_ID:cam1|CAM_OK:1|CAM_STATUS:OK|MODE:FUSED|CAP:40|CONF:0.812|OCC:0.325|CAB:MEDIUM|SEAT1_CAM:1|SEAT1_FINAL:TAKEN|MSGID:abcd1234
        """
        raw_data = raw_data.strip()

        if not self.active_train:
            return

        try:
            fields = {}
            for part in raw_data.split('|'):
                if ':' in part:
                    key, value = part.split(':', 1)
                    fields[key] = value

            # Required fields
            received_id = fields['ID']
            received_status = int(fields['S'])

            # New health/mode fields
            sonar_ok = int(fields['SONAR_OK']) if 'SONAR_OK' in fields else None
            sonar_status = fields.get('SONAR_STATUS')
            cam_id = fields.get('CAM_ID')
            cam_ok = int(fields['CAM_OK']) if 'CAM_OK' in fields else None
            cam_status = fields.get('CAM_STATUS')
            mode = fields.get('MODE')
            msg_id = fields.get('MSGID')

            # Existing/optional data fields
            capacity = self._safe_int_or_none(fields['CAP']) if 'CAP' in fields else None
            confidence_avg = self._safe_float_or_none(fields['CONF']) if 'CONF' in fields else None
            occupancy_ratio = self._safe_float_or_none(fields['OCC']) if 'OCC' in fields else None

            cabin_status_raw = fields.get('CAB')
            cabin_status = None if cabin_status_raw in (None, "UNKNOWN", "-1") else cabin_status_raw

            seat1_cam = self._safe_int_or_none(fields['SEAT1_CAM']) if 'SEAT1_CAM' in fields else None
            seat1_final_raw = fields.get('SEAT1_FINAL')
            seat1_final = None if seat1_final_raw in (None, "UNKNOWN", "-1") else seat1_final_raw

            # Convert ultrasonic display text
            if received_status == 1:
                ultrasonic_text = "TAKEN"
            elif received_status == 0:
                ultrasonic_text = "EMPTY"
            else:
                ultrasonic_text = "UNKNOWN"

            # Convert camera seat display text
            if seat1_cam == 1:
                seat1_cam_text = "TAKEN"
            elif seat1_cam == 0:
                seat1_cam_text = "EMPTY"
            else:
                seat1_cam_text = "UNKNOWN"

            print(f"\n[PARSED DATA]")
            print(f"   L Train ID: {received_id}")
            print(f"   L Ultrasonic Status: {ultrasonic_text}")

            if sonar_ok is not None:
                print(f"   L Sonar OK: {sonar_ok}")
            if sonar_status is not None:
                print(f"   L Sonar Status: {sonar_status}")
            if cam_id is not None:
                print(f"   L Camera ID: {cam_id}")
            if cam_ok is not None:
                print(f"   L Camera OK: {cam_ok}")
            if cam_status is not None:
                print(f"   L Camera Status: {cam_status}")
            if mode is not None:
                print(f"   L Mode: {mode}")

            if capacity is not None:
                print(f"   L Capacity: {capacity}")
            else:
                print(f"   L Capacity: UNAVAILABLE")

            if confidence_avg is not None:
                print(f"   L Confidence Average: {confidence_avg:.3f}")
            else:
                print(f"   L Confidence Average: UNAVAILABLE")

            if occupancy_ratio is not None:
                print(f"   L Occupancy Ratio: {occupancy_ratio:.3f}")
            else:
                print(f"   L Occupancy Ratio: UNAVAILABLE")

            print(f"   L Cabin Status: {cabin_status if cabin_status is not None else 'UNAVAILABLE'}")
            print(f"   L Camera Seat 1: {seat1_cam_text}")
            print(f"   L Final Seat 1: {seat1_final if seat1_final is not None else 'UNKNOWN'}")

            if msg_id is not None:
                print(f"   L Message ID: {msg_id}")

            if received_id == self.active_train:
                # Keep old dashboard update keys so current dashboard won't break
                self.dashboard_state.update(
                    active_train=received_id,
                    ultrasonic_status=ultrasonic_text,
                    capacity=capacity,
                    confidence_avg=confidence_avg,
                    occupancy_ratio=occupancy_ratio,
                    cabin_status=cabin_status,
                    seat1_cam=seat1_cam_text,
                    seat1_final=seat1_final
                )
            else:
                print(f"[IGNORE] Packet train ID {received_id} does not match active train {self.active_train}")

        except (IndexError, ValueError, KeyError):
            if "Heartbeat" in raw_data or "Ping" in raw_data or "CRC" in raw_data:
                pass
            else:
                print(f"[ERROR] Malformed packet received: {raw_data}")


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
                    # The firmware might output: "[RX] Data: ID:T01|S:1 | RSSI: ..."
                    if "[RX] Data: " in line:
                        parts = line.split("[RX] Data: ")
                        if len(parts) > 1:
                            payload_section = parts[1]
                            payload = payload_section.split(" | ")[0]
                            station.process_lora_packet(payload)
                    elif line.startswith("ID:") and "|S:" in line:
                        station.process_lora_packet(line)
                except Exception as e:
                    print(f"[SERIAL ERROR] {e}")
            time.sleep(0.1)
    except serial.SerialException:
        print(f"[WARNING] Could not open {port_name}. Running in Simulation-Only mode.")


def main():
    dashboard_state = DashboardState()
    station = StationReceiver(dashboard_state)

    # Start Flask in background thread
    app = create_flask_app(dashboard_state)
    web_thread = threading.Thread(target=flask_thread, args=(app,), daemon=True)
    web_thread.start()

    # Try to start serial listener in background
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

    print("--- STATION PI DASHBOARD SIMULATOR ---")
    print("Commands:")
    print("  ARRIVE <ID>  -> Simulate train arrival (e.g. 'ARRIVE T01')")
    print("  DEPART       -> Simulate train departure")
    print("  DATA <MSG>   -> Simulate receiving LoRa packet")
    print("  EXIT         -> Quit")
    print("----------------------------------------")

    try:
        while True:
            user_input = input("\nStation_Pi > ").strip().upper()

            if user_input.startswith("ARRIVE"):
                try:
                    parts = user_input.split()
                    if len(parts) > 1:
                        train_id = parts[1]
                        station.handle_arrival(train_id)
                    else:
                        print("[ERROR] Usage: ARRIVE <TrainID>")
                except ValueError:
                    print("[ERROR] Usage: ARRIVE <TrainID>")

            elif user_input == "DEPART":
                station.handle_departure()

            elif user_input.startswith("DATA"):
                if len(user_input) > 5:
                    raw_payload = user_input[5:]
                    station.process_lora_packet(raw_payload)
                else:
                    print("[ERROR] Usage: DATA ID:T01|S:1")

            elif user_input == "EXIT":
                print("Shutting down station...")
                break
            else:
                print("[ERROR] Unknown command.")

    except KeyboardInterrupt:
        print("\nShutting down station...")

if __name__ == "__main__":
    main()