import time, serial, queue, uuid
from ultrasonic import SonarSensor
from mqtt import MqttSubscriberThread
import lora_helper, sqlite_helper, camera_helper

# This file represents your "Main Application Logic"
# It runs on the main thread and imports the sensor driver

# ADDED: camera/broker health handling
PRIMARY_CAMERA_ID = "cam1"   # CHANGE THIS if your main camera ID is different
TX_INTERVAL_SECONDS = 20

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
    # This file represents your "Main Application Logic"
    
    # Initialize the sensor (starts its own background thread)
    sensor = SonarSensor()
    
    # Initialize Serial connection to LoRa module (PlatformIO device)
    lora_serial = lora_helper.connect_lora()

    # Create a Queue to hold the data from MQTT
    mqtt_queue = queue.Queue()

    # Keep latest state for each camera Pi
    camera_states = {}

    # initialize SQLite cache
    sqlite_helper.init_db()

    try:
        sensor.start()
        print(f"Main System Started for {train_id}. Sensor runs in background.")
        print(f"[SYSTEM] SQLite cache ready. Pending messages: {sqlite_helper.count_pending_messages()}")

        # Start MQTT Subscriber in a separate thread
        mqtt_thread = MqttSubscriberThread(mqtt_queue)
        mqtt_thread.start()
        
        # ==== Dennis's ====
        while True:
            # try reconnecting if LoRa is currently unavailable
            if (not lora_serial) or (hasattr(lora_serial, "is_open") and not lora_serial.is_open):
                lora_serial = lora_helper.connect_lora()

            # if LoRa link is back, resend cached messages first
            # if lora_serial:
            #     retry_ok = lora_helper.flush_cached_messages(lora_serial)
            #     if not retry_ok:
            #         try:
            #             lora_serial.close()
            #         except Exception:
            #             pass
            #         lora_serial = None

            # Update per-camera states from MQTT
            camera_helper.drain_camera_queue(mqtt_queue, camera_states)

            # --- sensor health snapshot ---
            sonar_ok = 1 if sensor.is_healthy() else 0
            sonar_status = sensor.get_health_status()
            
            # If sonar is unhealthy, do not trust its seat result
            seat_status = sensor.get_latest_status() if sonar_ok else -1
            distance = sensor.get_latest_distance()
            
            # --- camera health snapshot ---
            cam_state = camera_helper.get_effective_camera_state(camera_states, PRIMARY_CAMERA_ID, camera_helper.CAMERA_STALE_SECONDS)
            cam_ok = cam_state["cam_ok"]
            cam_status = cam_state["cam_status"]
            cam_data = cam_state["data"]
            cam_id = PRIMARY_CAMERA_ID

            # create unique ID for SQLite cache tracking
            msg_id = str(uuid.uuid4())[:8]

            print("=" * 10)
            print(f"[CAMERA STATES] {camera_helper.summarize_camera_states(camera_states)}")
            print(f"[SONAR] ok={sonar_ok} status={sonar_status} distance={distance:.2f}cm" if distance >= 0 else f"[SONAR] ok={sonar_ok} status={sonar_status} distance=INVALID")
            print(f"[PRIMARY CAMERA] id={cam_id} ok={cam_ok} status={cam_status}")

            # =========================
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

            msg = (
                f"ID:{train_id}"
                f"|S:{seat_status}"
                f"|CAP:{capacity}"
                f"|CONF:{fmt_float(confidence_avg)}"
                f"|OCC:{fmt_float(occupancy_ratio)}"
                f"|CAB:{cabin_status}"
                f"|SEAT1_CAM:{seat1_cam}"
                f"|SEAT1_FINAL:{final_seat1_status}"
            )
            print(f"\n[{TX_INTERVAL_SECONDS}s Cycle] Transmitting to Station: {msg}")
            print(f"   L Final Mode: {mode}")
            print(f"   L Final Seat 1 Status: {final_seat1_status}")
            print("=" * 10)

            # cache latest state first in SQLite
            sqlite_helper.cache_message(msg_id, msg)
            print(f"   [CACHE] Stored latest message {msg_id} in SQLite. Pending now: {sqlite_helper.count_pending_messages()}")

            # send only ONE packet this cycle: the latest cached one
            pending = sqlite_helper.get_one_pending_message()
        # ==== Dennis's ====

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
 
            
            # if lora_serial:
            #     ok = lora_helper.try_send_lora(lora_serial, msg)
            #     if ok:
            #         sqlite_helper.delete_cached_message(msg_id)
            #         print(f"   [SEND OK] Message {msg_id} sent and removed from SQLite cache.")
            #         # print(f"   [SEND OK] ok")
            #     else:
            #         print(f"   [SEND FAIL] Message {msg_id} kept in SQLite cache for retry.")
            #         # print(f"   [SEND OK] fail")
            #         try:
            #             lora_serial.close()
            #         except Exception:
            #             pass
            #         lora_serial = None
            # else:
            #     print(f"   [CACHE ONLY] No LoRa connection. Message {msg_id} kept in SQLite cache.")
            if pending is not None:
                outbound_id, outbound_msg = pending
            else:
                outbound_id, outbound_msg = msg_id, msg

            print(f"   [OUTBOUND] Sending one packet this cycle: {outbound_msg}")

            if lora_serial:
                ok = lora_helper.try_send_lora(lora_serial, outbound_msg)
                if ok:
                    sqlite_helper.delete_cached_message(outbound_id)
                    print(f"   [SEND OK] Message {outbound_id} sent and removed from SQLite cache.")
                else:
                    print(f"   [SEND FAIL] Message {outbound_id} kept in SQLite cache.")
                    try:
                        lora_serial.close()
                    except Exception:
                        pass
                    lora_serial = None
            else:
                print(f"   [CACHE ONLY] No LoRa connection. Latest message remains in SQLite cache.")

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
    # You can change this ID for different trains (e.g. T02, T03)
    main(train_id="T01")