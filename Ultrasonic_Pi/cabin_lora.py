import time, serial, queue, sqlite3, uuid, os
from ultrasonic import SonarSensor
from mqtt import MqttSubscriberThread

# This file represents your "Main Application Logic"
# It runs on the main thread and imports the sensor driver

# SQLite/cache config
DB_PATH = os.path.join(os.path.dirname(__file__), "lora_cache.db")
TX_INTERVAL_SECONDS = 20
RETRY_BATCH_SIZE = 10



# SQLite helper functions
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



# LoRa connection helpers
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



def main(train_id="T01"):
    # This file represents your "Main Application Logic"
    
    # Initialize the sensor (starts its own background thread)
    sensor = SonarSensor()
    
    # Initialize Serial connection to LoRa module (PlatformIO device)
    # lora_serial = None
    # try:
    #     # Common ports for Arduino/PlatformIO devices on Raspbian
    #     port_candidates = ['/dev/ttyACM0', '/dev/ttyUSB0', '/dev/ttyACM1', '/dev/ttyUSB1']
    #     for port in port_candidates:
    #         try:
    #             lora_serial = serial.Serial(port, 115200, timeout=1)
    #             print(f"[SYSTEM] Connected to LoRa module on {port}")
    #             break
    #         except serial.SerialException:
    #             pass
        
    #     if not lora_serial:
    #         print("[WARNING] No LoRa module found on standard ports. Running in Simulation Mode.")
    # except Exception as e:
    #     print(f"[ERROR] Serial setup failed: {e}")
    lora_serial = connect_lora()

    # Create a Queue to hold the data from MQTT
    mqtt_queue = queue.Queue()
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
            #try reconnecting if LoRa is currently unavailable
            if (not lora_serial) or (hasattr(lora_serial, "is_open") and not lora_serial.is_open):
                lora_serial = connect_lora()

            #if LoRa link is back, resend cached messages first
            if lora_serial:
                retry_ok = flush_cached_messages(lora_serial)
                if not retry_ok:
                    #close and force reconnect next round if send path looks broken
                    try:
                        lora_serial.close()
                    except Exception:
                        pass
                    lora_serial = None



            # --- YOUR MAIN LOGIC ---
            
            # 1. Pull latest data from sonar (Instant)
            # You can pull this anytime. The sensor updates itself ~5 times/sec in the background.
            seat_status = sensor.get_latest_status()    # 1 = TAKEN, 0 = EMPTY
            distance = sensor.get_latest_distance()
            
            # 2. Simulate LoRa Transmission
            # Packet Format: "ID:T01|S:1"
            # The '|' acts as a delimiter so the receiver can split the string easily
            # msg = f"ID:{train_id}|S:{seat_status}"
            #create a unique ID so cached messages can be tracked individually
            msg_id = str(uuid.uuid4())[:8]
            msg = f"ID:{train_id}|S:{seat_status}|MSGID:{msg_id}"

            print("=" * 10)
            
            status_desc = "TAKEN" if seat_status == 1 else "EMPTY"

            # if not mqtt_queue.empty():
            #     message_data = mqtt_queue.get()  # Retrieve the message from the queue
            #     print(f"   L Capacity: {message_data['capacity']}")
            #     print(f"   L Confidence Average: {message_data['confidence_avg']}")
            #     print(f"   L Occupancy Ratio: {message_data['occupancy_ratio']}")
            #     print(f"   L Cabin Status: {message_data['cabin_status']}")

            #     # Camera seat info
            #     seat1_status = message_data['roi_presence']['seat1']
            #     # seat2_status = message_data['roi_presence']['seat2']  # If second ultrasonic applied
            #     print(f"   L Seat 1: {seat1_status}")
            #     # print(f"   L Seat 2: {seat2_status}") 

            #     # Aggregated logic
            #     if seat_status == 0:
            #         final_seat1_status = "EMPTY"
            #     else:
            #         if seat1_status:
            #             final_seat1_status = "TAKEN"
            #         else:
            #             final_seat1_status = "OBJECT"
            #     print(f"   L Final Seat 1 Status: {final_seat1_status}")
            
            # drain queue and keep the latest MQTT message only
            # This avoids sending very stale camera data if queue has multiple items.
            latest_message_data = None
            while not mqtt_queue.empty():
                latest_message_data = mqtt_queue.get()

            if latest_message_data is not None:
                message_data = latest_message_data  # Retrieve latest camera-derived data
                print(f"   L Capacity: {message_data['capacity']}")
                print(f"   L Confidence Average: {message_data['confidence_avg']}")
                print(f"   L Occupancy Ratio: {message_data['occupancy_ratio']}")
                print(f"   L Cabin Status: {message_data['cabin_status']}")

                # Camera seat info
                seat1_status = message_data['roi_presence']['seat1']
                # seat2_status = message_data['roi_presence']['seat2']  # If second ultrasonic applied
                print(f"   L Seat 1: {seat1_status}")
                # print(f"   L Seat 2: {seat2_status}")

                # Aggregated logic
                if seat_status == 0:
                    final_seat1_status = "EMPTY"
                else:
                    if seat1_status:
                        final_seat1_status = "TAKEN"
                    else:
                        final_seat1_status = "OBJECT"
                print(f"   L Final Seat 1 Status: {final_seat1_status}")


                # Extended packet
                msg = (
                    f"ID:{train_id}"
                    f"|S:{seat_status}"
                    f"|CAP:{message_data['capacity']}"
                    f"|CONF:{message_data['confidence_avg']:.3f}"
                    f"|OCC:{message_data['occupancy_ratio']:.3f}"
                    f"|CAB:{message_data['cabin_status']}"
                    f"|SEAT1_CAM:{int(seat1_status)}"
                    f"|SEAT1_FINAL:{final_seat1_status}"
                    f"|MSGID:{msg_id}"
                )

                print(f"\n[20s Cycle] Transmitting to Station: {msg}")
                print(f"   L Raw Distance: {distance:.2f}cm")
                print(f"   L Interpretation: {status_desc} (<20cm is TAKEN)")
                print(f"   L Final Seat 1 Status: {final_seat1_status}")
                print("=" * 10)


                
            else:
                # fallback packet if no MQTT/camera data yet
                # msg = f"ID:{train_id}|S:{seat_status}"
                msg = f"ID:{train_id}|S:{seat_status}|MSGID:{msg_id}"
                print(f"\n[20s Cycle] Transmitting to Station: {msg}")
                print(f"   L Raw Distance: {distance:.2f}cm")
                print(f"   L Interpretation: {status_desc} (<20cm is TAKEN)")

                print("=" * 10)

            
            # Send to LoRa module if connected
            # if lora_serial:
            #     try:
            #         lora_serial.write((msg + '\n').encode('utf-8'))
            #         # Optional: Read response/debug from LoRa module
            #         # if lora_serial.in_waiting:
            #         #     print(f"   [LORA DEBUG] {lora_serial.readline().decode().strip()}")
            #     except Exception as e:
            #         print(f"   [ERROR] LoRa Write Failed: {e}")
            
            # NEW:
            # 1) cache first in SQLite
            # 2) try sending
            # 3) only delete from SQLite if send succeeds
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

            # 3. Wait for next cycle
            # This sleep doesn't block the sensor! It keeps measuring in its own thread.
            time.sleep(TX_INTERVAL_SECONDS)
            
    except KeyboardInterrupt:
        print("\nStopping Main System...")
    finally:
        # Always clean up the sensor thread on exit
        sensor.stop()
        if lora_serial:
            try:
                lora_serial.close()
            except Exception:
                pass

if __name__ == '__main__':
    # You can change this ID for different trains (e.g. T02, T03)
    main(train_id="T01")
