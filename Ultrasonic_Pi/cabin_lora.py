import time
import serial
import sys
from ultrasonic import SonarSensor

# This file represents your "Main Application Logic"
# It runs on the main thread and imports the sensor driver

def main(train_id="T01"):
    # This file represents your "Main Application Logic"
    
    # Initialize the sensor (starts its own background thread)
    sensor = SonarSensor()
    
    # Initialize Serial connection to LoRa module (PlatformIO device)
    lora_serial = None
    try:
        # Common ports for Arduino/PlatformIO devices on Raspbian
        port_candidates = ['/dev/ttyACM0', '/dev/ttyUSB0', '/dev/ttyACM1', '/dev/ttyUSB1']
        for port in port_candidates:
            try:
                lora_serial = serial.Serial(port, 115200, timeout=1)
                print(f"[SYSTEM] Connected to LoRa module on {port}")
                break
            except serial.SerialException:
                pass
        
        if not lora_serial:
            print("[WARNING] No LoRa module found on standard ports. Running in Simulation Mode.")
    except Exception as e:
        print(f"[ERROR] Serial setup failed: {e}")

    try:
        sensor.start()
        print(f"Main System Started for {train_id}. Sensor runs in background.")
        
        while True:
            # --- YOUR MAIN LOGIC ---
            
            # 1. Pull latest data from sonar (Instant)
            # You can pull this anytime. The sensor updates itself ~5 times/sec in the background.
            seat_status = sensor.get_latest_status()
            distance = sensor.get_latest_distance()
            
            # 2. Simulate LoRa Transmission
            # Packet Format: "ID:T01|S:1"
            # The '|' acts as a delimiter so the receiver can split the string easily
            msg = f"ID:{train_id}|S:{seat_status}"
            
            status_desc = "TAKEN" if seat_status == 1 else "EMPTY"
            print(f"\n[20s Cycle] Transmitting to Station: {msg}")
            print(f"   L Raw Distance: {distance:.2f}cm")
            print(f"   L Interpretation: {status_desc} (<20cm is TAKEN)")
            
            # Send to LoRa module if connected
            if lora_serial:
                try:
                    lora_serial.write((msg + '\n').encode('utf-8'))
                    # Optional: Read response/debug from LoRa module
                    # if lora_serial.in_waiting:
                    #     print(f"   [LORA DEBUG] {lora_serial.readline().decode().strip()}")
                except Exception as e:
                    print(f"   [ERROR] LoRa Write Failed: {e}")

            # 3. Wait for next cycle
            # This sleep doesn't block the sensor! It keeps measuring in its own thread.
            time.sleep(20) 
            
    except KeyboardInterrupt:
        print("\nStopping Main System...")
    finally:
        # Always clean up the sensor thread on exit
        sensor.stop()
        if lora_serial:
            lora_serial.close()

if __name__ == '__main__':
    # You can change this ID for different trains (e.g. T02, T03)
    main(train_id="T01")
