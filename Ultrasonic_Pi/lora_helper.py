import serial, sqlite_helper

RETRY_BATCH_SIZE = 10

# =========================
# LoRa connection helpers
# =========================
def connect_lora():
    """Try to connect to LoRa module on common serial ports."""
    try:
        port_candidates = ['/dev/ttyACM0', '/dev/ttyUSB0', '/dev/ttyACM1', '/dev/ttyUSB1']
        # port_candidates = ['/dev/ttyACM0', '/dev/ttyUSB0', '/dev/ttyACM1', '/dev/ttyUSB1', '/dev/ttyAMA10']
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
        print("[PAYLOAD] ", payload)
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

    pending_rows = sqlite_helper.get_pending_messages(RETRY_BATCH_SIZE)
    if not pending_rows:
        return True

    print(f"[RETRY] Found {len(pending_rows)} cached message(s) in SQLite.")

    for cached_msg_id, cached_payload in pending_rows:
        ok = try_send_lora(lora_serial, cached_payload)
        if ok:
            sqlite_helper.delete_cached_message(cached_msg_id)
            print(f"   [RETRY OK] Sent cached message {cached_msg_id}")
        else:
            print(f"   [RETRY STOP] Cached message {cached_msg_id} still cannot be sent.")
            return False

    return True