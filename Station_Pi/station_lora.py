import time, serial, threading, sys
from dashboard_web.app import DashboardState, create_flask_app, flask_thread

class StationReceiver:
    def __init__(self, dashboard_state):
        self.active_train = None
        self.seat_status = None # None means unconfirmed
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

    def process_lora_packet(self, raw_data):
        """
        Parses incoming LoRa data.

        Full packet example:
        ID:T01|S:1|CAP:40|CONF:0.812|OCC:0.325|CAB:MEDIUM|SEAT1_CAM:1|SEAT1_FINAL:TAKEN|MSGID:abcd1234

        Fallback packet example:
        ID:T01|S:1|MSGID:abcd1234
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

            # Optional fields
            capacity = int(fields['CAP']) if 'CAP' in fields else None
            confidence_avg = float(fields['CONF']) if 'CONF' in fields else None
            occupancy_ratio = float(fields['OCC']) if 'OCC' in fields else None
            cabin_status = fields.get('CAB')
            seat1_cam = int(fields['SEAT1_CAM']) if 'SEAT1_CAM' in fields else None
            seat1_final = fields.get('SEAT1_FINAL')
            msg_id = fields.get('MSGID')  # optional, safe to ignore if unused

            ultrasonic_text = "TAKEN" if received_status == 1 else "EMPTY"
            seat1_cam_text = (
                "TAKEN" if seat1_cam == 1 else
                "EMPTY" if seat1_cam == 0 else
                "UNKNOWN"
            )

            print(f"\n[PARSED DATA]")
            print(f"   L Train ID: {received_id}")
            print(f"   L Ultrasonic Status: {ultrasonic_text}")
            if capacity is not None:
                print(f"   L Capacity: {capacity}")
            if confidence_avg is not None:
                print(f"   L Confidence Average: {confidence_avg:.3f}")
            if occupancy_ratio is not None:
                print(f"   L Occupancy Ratio: {occupancy_ratio:.3f}")
            if cabin_status is not None:
                print(f"   L Cabin Status: {cabin_status}")
            if seat1_cam is not None:
                print(f"   L Camera Seat 1: {seat1_cam_text}")
            if seat1_final is not None:
                print(f"   L Final Seat 1: {seat1_final}")
            if msg_id is not None:
                print(f"   L Message ID: {msg_id}")

            if received_id == self.active_train:
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
                    # The firmware might output: "[RX] Data: ID:T01|S:1 | RSSI: ..."
                    if "[RX] Data: " in line:
                        # Extract just the payload part
                        parts = line.split("[RX] Data: ")
                        if len(parts) > 1:
                            payload_section = parts[1]
                            # Stop at the "|" RSSI delimiter if present
                            payload = payload_section.split(" | ")[0]
                            station.process_lora_packet(payload)
                    # OR it might be raw transparent data: "ID:T01|S:1"
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
    # Raspbian typically uses /dev/ttyACM0 or USB0 for Arduinos
    port_candidates = ['/dev/ttyACM0', '/dev/ttyUSB0', 'COM3', 'COM4'] 
    
    # Basic port detection logic (or just try the first known one)
    # For now, we launch the thread and it will try to connect once.
    # To improve, you might want to iterate candidates, 
    # but threading args is simpler if we just pick one likely one for now.
    
    # We'll just try connecting to the first available one in the list or let the user specify?
    # Simple approach: Try valid ports in loop locally before threading
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
    print("  DATA <MSG>   -> Simulate receiving LoRa packet (e.g. 'DATA ID:T01|S:1')")
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
                # Simulate the LoRa radio receiving a string
                # Remove "DATA " from the start to get the raw payload
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
