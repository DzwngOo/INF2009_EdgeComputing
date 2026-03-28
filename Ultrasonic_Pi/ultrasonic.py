import RPi.GPIO as GPIO
import time
import threading

# --- CONFIGURATION ---
TRIG = 23
ECHO = 24
# ---------------------

class SonarSensor:
    def __init__(self):
        self.current_status = 0   # 0: Vacant, 1: Occupied
        self.current_distance = -1.0

        # ADDED: health tracking
        self.sensor_ok = False
        self.sensor_status = "STARTING"
        self.last_valid_ts = 0.0
        self.fail_count = 0
        self.max_fail_count = 5
        self.stale_timeout = 2.0  # seconds without valid reading => unhealthy

        self.running = False
        self._thread = None
        self._setup_gpio()

    def _setup_gpio(self):
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(TRIG, GPIO.OUT)
        GPIO.setup(ECHO, GPIO.IN)
        GPIO.output(TRIG, False)
        time.sleep(0.5)

    def _read_raw_distance(self):
        gpio_in = GPIO.input
        timer = time.perf_counter

        GPIO.output(TRIG, True)
        time.sleep(0.00001)
        GPIO.output(TRIG, False)

        pulse_start = timer()
        pulse_end = timer()

        timeout = timer() + 0.04  # 40ms timeout ~ 6.8m

        while gpio_in(ECHO) == 0:
            pulse_start = timer()
            if pulse_start > timeout:
                return -1

        while gpio_in(ECHO) == 1:
            pulse_end = timer()
            if pulse_end > timeout:
                return -1

        duration = pulse_end - pulse_start
        return duration * 17150

    def _get_stable_distance(self):
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

    def _mark_sensor_failed(self, status_text="TIMEOUT"):
        self.fail_count += 1
        self.current_distance = -1.0

        # OLD:
        # no explicit sensor health/failure state
        #
        # NEW:
        if self.fail_count >= self.max_fail_count:
            self.sensor_ok = False
            self.sensor_status = status_text

        # stale check in case last valid reading is too old
        if self.last_valid_ts > 0 and (time.time() - self.last_valid_ts) > self.stale_timeout:
            self.sensor_ok = False
            self.sensor_status = status_text

    def _loop(self):
        """Background thread to continuously update status"""
        while self.running:
            try:
                dist = self._get_stable_distance()

                if dist > 0:
                    new_status = 1 if dist < 20 else 0
                    self.current_status = new_status
                    self.current_distance = dist

                    # ADDED: mark sensor healthy on valid readings
                    self.sensor_ok = True
                    self.sensor_status = "OK"
                    self.last_valid_ts = time.time()
                    self.fail_count = 0
                else:
                    # ADDED: invalid reading now affects health state
                    self._mark_sensor_failed("TIMEOUT")

                time.sleep(0.2)

            except Exception as e:
                print(f"Sonar Error: {e}")

                # ADDED: exception also marks sonar unhealthy
                self.sensor_ok = False
                self.sensor_status = f"ERROR:{e}"
                self.current_distance = -1.0
                self.fail_count += 1

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

    # ADDED: broker can now check sonar health explicitly
    def is_healthy(self):
        return self.sensor_ok

    # ADDED: broker can report why sonar is unhealthy
    def get_health_status(self):
        return self.sensor_status

    # ADDED: useful if you want staleness logic/debugging later
    def get_last_valid_age(self):
        if self.last_valid_ts <= 0:
            return None
        return time.time() - self.last_valid_ts