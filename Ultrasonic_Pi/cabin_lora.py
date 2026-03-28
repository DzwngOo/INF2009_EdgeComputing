import time, serial, queue
from ultrasonic import SonarSensor
from mqtt import MqttSubscriberThread

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

    # Create a Queue to hold the data from MQTT
    mqtt_queue = queue.Queue()

    try:
        sensor.start()
        print(f"Main System Started for {train_id}. Sensor runs in background.")

        # Start MQTT Subscriber in a separate thread
        mqtt_thread = MqttSubscriberThread(mqtt_queue)
        mqtt_thread.start()
        
        # ==== Deric's ====
        while True:
            # --- YOUR MAIN LOGIC ---
            
            # 1. Pull latest data from sonar (Instant)
            # You can pull this anytime. The sensor updates itself ~5 times/sec in the background.
            seat_status = sensor.get_latest_status()    # 1 = TAKEN, 0 = EMPTY
            distance = sensor.get_latest_distance()
            
            # 2. Simulate LoRa Transmission
            # Packet Format: "ID:T01|S:1"
            # The '|' acts as a delimiter so the receiver can split the string easily
            msg = f"ID:{train_id}|S:{seat_status}"

            print("=" * 10)
            
            status_desc = "TAKEN" if seat_status == 1 else "EMPTY"
            message_data = None
            while not mqtt_queue.empty():
                message_data = mqtt_queue.get()

            if message_data is not None:
                print(f"   L Capacity: {message_data['capacity']}")
                print(f"   L Confidence Average: {message_data['confidence_avg']}")
                print(f"   L Occupancy Ratio: {message_data['occupancy_ratio']}")
                print(f"   L Cabin Status: {message_data['cabin_status']}")

                seat1_status = message_data['roi_presence']['seat1']
                final_seat1_status = "EMPTY" if seat_status == 0 else ("TAKEN" if seat1_status else "OBJECT")

                msg = (
                    f"ID:{train_id}"
                    f"|S:{seat_status}"
                    f"|CAP:{message_data['capacity']}"
                    f"|CONF:{message_data['confidence_avg']:.3f}"
                    f"|OCC:{message_data['occupancy_ratio']:.3f}"
                    f"|CAB:{message_data['cabin_status']}"
                    f"|SEAT1_CAM:{int(seat1_status)}"
                    f"|SEAT1_FINAL:{final_seat1_status}"
                )

                print(f"\n[20s Cycle] Transmitting to Station: {msg}")
                print(f"   L Raw Distance: {distance:.2f}cm")
                print(f"   L Interpretation: {status_desc} (<20cm is TAKEN)")
                print(f"   L Final Seat 1 Status: {final_seat1_status}")

            else:
                msg = f"ID:{train_id}|S:{seat_status}"
                print(f"\n[20s Cycle] Transmitting to Station: {msg}")
                print(f"   L Raw Distance: {distance:.2f}cm")
                print(f"   L Interpretation: {status_desc} (<20cm is TAKEN)")
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
            
            # Send to LoRa module if connected
            if lora_serial:
                try:
                    print(msg)
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