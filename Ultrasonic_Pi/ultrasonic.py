import RPi.GPIO as GPIO
import time
import threading

# --- CONFIGURATION ---
TRIG = 23
ECHO = 24
# ---------------------

class SonarSensor:
    def __init__(self):
        self.current_status = 0 # 0: Vacant, 1: Occupied
        self.current_distance = 0.0
        self.running = False
        self._thread = None
        self._setup_gpio()

    def _setup_gpio(self):
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(TRIG, GPIO.OUT)
        GPIO.setup(ECHO, GPIO.IN)
        GPIO.output(TRIG, False)
        # Allow a little settling time if needed
        time.sleep(0.5)

    def _read_raw_distance(self):
        # Optimization: Local variable references
        gpio_in = GPIO.input
        timer = time.perf_counter
        
        GPIO.output(TRIG, True)
        time.sleep(0.00001)
        GPIO.output(TRIG, False)

        pulse_start = timer()
        pulse_end = timer()
        
        # 40ms timeout ~ 6.8m
        timeout = timer() + 0.04 
        
        while gpio_in(ECHO) == 0:
            pulse_start = timer()
            if pulse_start > timeout: return -1

        while gpio_in(ECHO) == 1:
            pulse_end = timer()
            if pulse_end > timeout: return -1

        duration = pulse_end - pulse_start
        return duration * 17150

    def _get_stable_distance(self):
        # Median of 5 readings
        readings = []
        for _ in range(5):
            d = self._read_raw_distance()
            if 2 < d < 400:
                readings.append(d)
            time.sleep(0.01)
        
        if readings:
            readings.sort()
            return readings[len(readings) // 2]
        return -1

    def _loop(self):
        """Background thread to continuously update status"""
        while self.running:
            try:
                dist = self._get_stable_distance()
                
                if dist > 0:
                    # Logic: < 20cm is Occupied (1), else Vacant (0)
                    new_status = 1 if dist < 20 else 0
                    self.current_status = new_status
                    self.current_distance = dist
                
                # Update rate: ~5Hz (every 0.2s)
                time.sleep(0.2)
            except Exception as e:
                print(f"Sonar Error: {e}")
                time.sleep(1)

    def start(self):
        """Start the background monitoring thread"""
        if not self.running:
            self.running = True
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            print("SonarSensor: Monitoring started in background.")

    def stop(self):
        """Stop the background monitoring thread"""
        self.running = False
        if self._thread:
            self._thread.join()
        GPIO.cleanup()
        print("SonarSensor: Stopped.")

    def get_latest_status(self):
        """
        Returns the latest held value.
        0 = Vacant
        1 = Occupied
        """
        return self.current_status

    def get_latest_distance(self):
        """Returns the latest distance reading in cm"""
        return self.current_distance
