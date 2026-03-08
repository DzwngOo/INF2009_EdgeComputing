#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>

/*
  SIMPLE STATION (RECEIVER) SKETCH
  --------------------------------
  Listens for incoming LoRa packets.
  
  LED STATUS:
  1. SOLID ON (1s) -> Boot Up
  2. SOS PATTERN   -> Radio Init Failed
  3. SHORT BLIP    -> Packet Received & Validated!
*/

// LED Pin
#ifndef RAD_LED
  #define RAD_LED 37
#endif

// LoRa Pins (LilyGo T3S3 SX1280)
#define LORA_SCK    5
#define LORA_MISO   3
#define LORA_MOSI   6
#define LORA_CS     7
#define LORA_RST    8
#define LORA_DIO1   9
#define LORA_BUSY   36

// SX1280 radio = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);
Module* radioModule = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);
SX1280 radio(radioModule);

// Globals
volatile bool receivedFlag = false;
volatile bool enableInterrupt = true;

// Interrupt Service Routine
#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void setFlag(void) {
  if(!enableInterrupt) return;
  receivedFlag = true;
}

void setup() {
  pinMode(RAD_LED, OUTPUT);
  Serial.begin(115200);
  delay(3000); 
  Serial.println("\n--- Station Booting (Non-Blocking) ---");
  
  // Power-on Indicator
  digitalWrite(RAD_LED, HIGH);
  delay(1000);
  digitalWrite(RAD_LED, LOW);

  // Initialize SPI
  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI);

  // Initialize Radio
  Serial.print("[INFO] Initializing Radio... ");
  
  #if defined(SX1280_RXEN) && defined(SX1280_TXEN)
    radioModule->setRfSwitchPins(SX1280_RXEN, SX1280_TXEN);
    Serial.print("(PA/LNA Enabled) ");
  #endif

  int state = radio.begin(2400.0, 406.25, 7, 5, 0x12, 10, 12);

  if (state == RADIOLIB_ERR_NONE) {
    Serial.println("Success!");
    radio.setDio1Action(setFlag);
    
    // Start Listening
    Serial.print("[INFO] Starting to listen... ");
    state = radio.startReceive();
    if (state == RADIOLIB_ERR_NONE) {
      Serial.println("Started!");
    } else {
      Serial.print("Failed to start receive, code ");
      Serial.println(state);
    }
  } else {
    Serial.print("Failed, code ");
    Serial.println(state);
    while (true) {
       for(int i=0; i<3; i++) { digitalWrite(RAD_LED, HIGH); delay(100); digitalWrite(RAD_LED, LOW); delay(100); }
       delay(500); 
    }
  }
}

void loop() {
  // 1. Check if packet received
  if (receivedFlag) {
    enableInterrupt = false;
    receivedFlag = false;
    
    String str;
    int state = radio.readData(str);

    if (state == RADIOLIB_ERR_NONE) {
       // Packet received successfully
       Serial.print("[RX] Data: ");
       Serial.print(str);
       Serial.print(" | RSSI: ");
       Serial.print(radio.getRSSI());
       Serial.print(" dBm | SNR: ");
       Serial.print(radio.getSNR());
       Serial.println(" dB");
       
       // Visual Flash
       digitalWrite(RAD_LED, HIGH);
       delay(50);
       digitalWrite(RAD_LED, LOW);
       
    } else if (state == RADIOLIB_ERR_CRC_MISMATCH) {
      Serial.println("[ERR] CRC Error");
    } else {
      Serial.print("[ERR] Read failed: ");
      Serial.println(state);
    }

    // Restart Listening
    radio.startReceive();
    enableInterrupt = true;
  }

  // 2. Heartbeat (so you know it's alive)
  static unsigned long lastHeartbeat = 0;
  if (millis() - lastHeartbeat > 2000) {
    lastHeartbeat = millis();
    Serial.println("."); // Just a dot to show it's alive
  }
}
