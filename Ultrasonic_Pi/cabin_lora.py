import time, serial, queue, uuid
from ultrasonic import SonarSensor
from mqtt import MqttSubscriberThread
import sqlite_helper

TX_INTERVAL_SECONDS = 5

# =========================
# LoRa helper functions
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


def send_lora_message(lora_serial, payload):
    """
    Attempt to send payload over LoRa.
    Returns True on success, False on failure.

    Note:
    This only confirms the local serial/module write succeeded.
    It does NOT confirm the remote receiver got the packet.
    For true delivery confirmation, you need an ACK from the receiver.
    """
    if not lora_serial:
        print("[ERROR] No LoRa serial available.")
        return False

    try:
        print(payload)
        lora_serial.write((payload + '\n').encode('utf-8'))
        print("[LoRa] Message sent successfully.")
        return True
    except Exception as e:
        print(f"[ERROR] LoRa Write Failed: {e}")
        return False
    
def wait_for_ack(lora_serial, train_id, msg_id, timeout=1.5):
    """Wait briefly for matching ACK from station."""
    if not lora_serial:
        return False

    end_time = time.time() + timeout

    while time.time() < end_time:
        try:
            if lora_serial.in_waiting:
                line = lora_serial.readline().decode('utf-8', errors='ignore').strip()
                print(f"[CABIN RAW] {line}")

                expected_ack = f"ACK|ID:{train_id}|MSGID:{msg_id}"
                if line == expected_ack:
                    print(f"[CABIN ACK] {line}")
                    return True
        except Exception as e:
            print(f"[CABIN ACK ERROR] {e}")
            return False

        time.sleep(0.05)

    print(f"[CABIN ACK TIMEOUT] No ACK for MSGID {msg_id}")
    return False

def main(train_id="T01"):
    sqlite_helper.init_db()
    
    # Initialize the sensor (starts its own background thread)
    # sensor = SonarSensor()
    sensor1 = SonarSensor(trig_pin=23, echo_pin=24) # 1st seat
    sensor2 = SonarSensor(trig_pin=17, echo_pin=27) # 2nd seat
    
    # Initialize Serial connection to LoRa module (PlatformIO device)
    lora_serial = connect_lora()

    # Create a Queue to hold the data from MQTT
    mqtt_queue = queue.Queue()

    try:
        sensor1.start()
        sensor2.start()
        print(f"Main System Started for {train_id}. Sensors run in background.")

        mqtt_thread = MqttSubscriberThread(mqtt_queue)
        mqtt_thread.start()

        while True:
            seat_status1 = sensor1.get_latest_status()
            distance1 = sensor1.get_latest_distance()

            seat_status2 = sensor2.get_latest_status()
            distance2 = sensor2.get_latest_distance()

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

                msg_id = str(uuid.uuid4())[:8]
                msg = (
                    f"ID:{train_id}"
                    f"|MSGID:{msg_id}"
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
                )

                print(f"\n[20s Cycle] Transmitting to Station: {msg}")
                print(f"   L Seat 1 Raw Distance: {distance1:.2f}cm")
                print(f"   L Seat 1 Interpretation: {status_desc1} (<20cm is TAKEN)")
                print(f"   L Final Seat 1 Status: {final_seat1_status}")

                print(f"   L Seat 2 Raw Distance: {distance2:.2f}cm")
                print(f"   L Seat 2 Interpretation: {status_desc2} (<20cm is TAKEN)")
                print(f"   L Final Seat 2 Status: {final_seat2_status}")

            else:
                msg_id = str(uuid.uuid4())[:8]
                msg = (
                    f"ID:{train_id}"
                    f"|MSGID:{msg_id}"
                    f"|S1:{seat_status1}"
                    f"|S2:{seat_status2}"
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
            
            # Send to LoRa module if connected
            # =========================
            # Latest-only SQLite fallback logic
            # =========================
            cached_msg = sqlite_helper.get_cached_message()

            if cached_msg is not None:
                print("[SQLITE] Cached message exists. Trying cached latest message first...")

                cached_msg_id = None
                for part in cached_msg.split('|'):
                    if part.startswith("MSGID:"):
                        cached_msg_id = part.split(":", 1)[1]
                        break

                if send_lora_message(lora_serial, cached_msg) and cached_msg_id and wait_for_ack(lora_serial, train_id, cached_msg_id):
                    sqlite_helper.clear_cached_message()
                    time.sleep(TX_INTERVAL_SECONDS)
                    continue
                else:
                    sqlite_helper.cache_latest_message(msg)
                    time.sleep(TX_INTERVAL_SECONDS)
                    continue

            if send_lora_message(lora_serial, msg):
                if not wait_for_ack(lora_serial, train_id, msg_id):
                    sqlite_helper.cache_latest_message(msg)
            else:
                sqlite_helper.cache_latest_message(msg)

            time.sleep(TX_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\nStopping Main System...")

    finally:
        sensor1.stop()
        sensor2.stop()
        if lora_serial:
            lora_serial.close()

if __name__ == '__main__':
    # You can change this ID for different trains (e.g. T02, T03)
    main(train_id="T01")