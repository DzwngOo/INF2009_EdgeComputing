import RPi.GPIO as GPIO
import time
import threading

class SonarSensor:
    # Shared lock prevents two ultrasonic modules from pinging at the same time.
    _trigger_lock = threading.Lock()

    def __init__(
        self,
        trig_pin,
        echo_pin,
        occupied_threshold_cm=20,
        min_valid_cm=3.0,
        max_valid_cm=400.0,
        invalid_hold_s=1.5,
        status_change_confirmations=2,
    ):
        self.trig_pin = trig_pin
        self.echo_pin = echo_pin
        self.occupied_threshold_cm = occupied_threshold_cm
        self.min_valid_cm = float(min_valid_cm)
        self.max_valid_cm = float(max_valid_cm)
        self.invalid_hold_s = float(invalid_hold_s)
        self.status_change_confirmations = max(1, int(status_change_confirmations))

        self.current_status = 0   # 0: Vacant, 1: Occupied
        self.current_distance = -1.0
        self.distance_valid = False
        self.running = False
        self._thread = None

        self._last_valid_distance = -1.0
        self._last_valid_time = 0.0
        self._pending_status = None
        self._pending_status_count = 0

        self._setup_gpio()

    def _setup_gpio(self):
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.trig_pin, GPIO.OUT)
        GPIO.setup(self.echo_pin, GPIO.IN)
        GPIO.output(self.trig_pin, False)
        time.sleep(0.5)

    def _read_raw_distance(self):
        gpio_in = GPIO.input
        timer = time.perf_counter

        with SonarSensor._trigger_lock:
            GPIO.output(self.trig_pin, False)
            time.sleep(0.0002)

            GPIO.output(self.trig_pin, True)
            time.sleep(0.00001)
            GPIO.output(self.trig_pin, False)

            pulse_start = timer()
            pulse_end = timer()
            timeout = timer() + 0.04

            while gpio_in(self.echo_pin) == 0:
                pulse_start = timer()
                if pulse_start > timeout:
                    return -1

            while gpio_in(self.echo_pin) == 1:
                pulse_end = timer()
                if pulse_end > timeout:
                    return -1

        duration = pulse_end - pulse_start
        return duration * 17150

    def _get_stable_distance(self):
        readings = []
        for _ in range(5):
            d = self._read_raw_distance()
            if self.min_valid_cm < d < self.max_valid_cm:
                readings.append(d)
            time.sleep(0.01)

        if readings:
            readings.sort()
            return readings[len(readings) // 2]
        return -1

    def _update_status_with_hysteresis(self, candidate_status):
        if candidate_status == self.current_status:
            self._pending_status = None
            self._pending_status_count = 0
            return

        if candidate_status != self._pending_status:
            self._pending_status = candidate_status
            self._pending_status_count = 1
        else:
            self._pending_status_count += 1

        if self._pending_status_count >= self.status_change_confirmations:
            self.current_status = candidate_status
            self._pending_status = None
            self._pending_status_count = 0

    def _loop(self):
        while self.running:
            try:
                dist = self._get_stable_distance()
                now = time.perf_counter()

                if dist > 0:
                    new_status = 1 if dist < self.occupied_threshold_cm else 0
                    self._update_status_with_hysteresis(new_status)

                    self.current_distance = dist
                    self.distance_valid = True
                    self._last_valid_distance = dist
                    self._last_valid_time = now
                else:
                    hold_recent = (
                        self._last_valid_time > 0
                        and (now - self._last_valid_time) <= self.invalid_hold_s
                        and self._last_valid_distance > 0
                    )

                    self.distance_valid = False
                    if hold_recent:
                        # Keep the last valid value briefly to avoid flicker on occasional no-echo cycles.
                        self.current_distance = self._last_valid_distance
                    else:
                        self.current_distance = -1.0
                        self._pending_status = None
                        self._pending_status_count = 0

                time.sleep(0.2)
            except Exception as e:
                print(f"Sonar Error on TRIG={self.trig_pin}, ECHO={self.echo_pin}: {e}")
                time.sleep(1)

    def start(self):
        if not self.running:
            self.running = True
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            print(f"SonarSensor: Monitoring started on TRIG={self.trig_pin}, ECHO={self.echo_pin}")

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join()
        print(f"SonarSensor: Stopped on TRIG={self.trig_pin}, ECHO={self.echo_pin}")

    def get_latest_status(self):
        return self.current_status

    def get_latest_distance(self):
        return self.current_distance

    def get_latest_distance_valid(self):
        return self.distance_valid

    @staticmethod
    def cleanup_gpio():
        GPIO.cleanup()
        print("GPIO cleaned up.")