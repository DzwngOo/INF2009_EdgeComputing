import time
import serial
import threading
import sys

class StationReceiver:
    def __init__(self):
        self.active_train = None
        self.seat_status = None # None means unconfirmed

    def handle_arrival(self, train_id):
        """Simulate a train arriving and locking onto its signal."""
        print(f"\n[EVENT] Train {train_id} has arrived at the platform.")
        print(f"[SYSTEM] Creating secure link to {train_id}...")
        self.active_train = train_id
        self.seat_status = None

    def handle_departure(self):
        """Simulate the train leaving."""
        if self.active_train:
            print(f"\n[EVENT] Train {self.active_train} has departed.")
            print("[SYSTEM] Closing link. Returning to IDLE mode.")
            self.active_train = None
            self.seat_status = None
        else:
            print("[ERROR] No train is currently at the platform.")

    def process_lora_packet(self, raw_data):
        """
        Parses incoming LoRa data.
        Expected format: "ID:T01|S:1"
        """
        # Trim potential whitespace
        raw_data = raw_data.strip()
        
        if not self.active_train:
            # Uncomment to debug ignored packets
            # print(f"[IGNORE] Received '{raw_data}' but no train is at platform.")
            return

        try:
            # Parse the string "ID:T01|S:1"
            parts = raw_data.split('|')
            received_id = parts[0].split(':')[1]
            received_status = int(parts[1].split(':')[1])

            # Logic: Only update if the ID matches the train at the platform
            if received_id == self.active_train:
                # Only print update if status changed or it's the first confirm
                if self.seat_status != received_status:
                    self.seat_status = received_status
                    status_str = "TAKEN" if self.seat_status == 1 else "EMPTY"
                    print(f"\n[UPDATE] Verified {received_id}: Seat is {status_str}")
                    print("Station_Pi > ", end="", flush=True) # Reprint prompt
            else:
                pass 
                # print(f"[IGNORE] Received data from {received_id}, but looking for {self.active_train}.")
                
        except (IndexError, ValueError):
            # Ignore heartbeat/debug messages that are not valid data
            if "Heartbeat" in raw_data or "Ping" in raw_data or "CRC" in raw_data:
                 pass # Silently ignore these known debug packets
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
    station = StationReceiver()
    
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
