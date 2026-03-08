import RPi.GPIO as GPIO
import time
import serial
import sys

# --- CONFIGURATION ---
# Physical Pin 1  -> VCC (Note: Standard HC-SR04 needs 5V/Pin 2. pin 1 is 3.3V)
# Physical Pin 6  -> GND
# Physical Pin 16 (GPIO 23) -> Trig
TRIG = 23
# Physical Pin 18 (GPIO 24) -> Echo
ECHO = 24
# Serial Port for connecting to ESP32 (usually /dev/ttyACM0 or /dev/ttyUSB0)
SERIAL_PORT = '/dev/ttyACM0'  
BAUD_RATE = 115200
# ---------------------

def setup():
    # Use BCM GPIO numbering
    GPIO.setmode(GPIO.BCM)
    
    # Set up the sensor pins
    GPIO.setup(TRIG, GPIO.OUT)
    GPIO.setup(ECHO, GPIO.IN)
    
    # Ensure trigger is low
    GPIO.output(TRIG, False)
    print("Waiting for sensor to settle...")
    time.sleep(2)

def get_distance():
    # Send 10us pulse to trigger
    GPIO.output(TRIG, True)
    time.sleep(0.00001)
    GPIO.output(TRIG, False)

    pulse_start = time.time()
    pulse_end = time.time()
    
    timeout = time.time() + 0.1 # 100ms timeout

    # Record the last low timestamp before the echo starts
    while GPIO.input(ECHO) == 0:
        pulse_start = time.time()
        if pulse_start > timeout:
            return -1

    # Record the last high timestamp (end of echo)
    while GPIO.input(ECHO) == 1:
        pulse_end = time.time()
        if pulse_end > timeout:
            return -1

    duration = pulse_end - pulse_start
    # Speed of sound is 34300 cm/s
    # Distance = (Time * Speed) / 2
    distance = duration * 17150
    return round(distance, 2)

def main():
    setup()
    
    ser = None
    try:
        # Open serial connection to ESP32
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        ser.flush()
        print(f"Connected to ESP32 on {SERIAL_PORT}")
    except Exception as e:
        print(f"Error connecting to Serial: {e}")
        print("Check if the ESP32 is plugged in and recognized (ls /dev/tty*)")
        return

    try:
        while True:
            dist = get_distance()
            
            if dist > 0 and dist < 400: # Valid range 2cm - 400cm
                message = f"D:{dist}cm\n"
                print(f"Sending: {message.strip()}")
                
                # Send to ESP32 over USB Serial
                ser.write(message.encode('utf-8'))
            else:
                print("Out of range or error")
            
            # Wait 1 second before next reading
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping...")
        GPIO.cleanup()
        if ser:
            ser.close()

if __name__ == '__main__':
    main()
