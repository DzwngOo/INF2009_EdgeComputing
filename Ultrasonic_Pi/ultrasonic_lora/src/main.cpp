// #include <Arduino.h>
// #include <SPI.h>
// #include <RadioLib.h>

// /*
//   DIAGNOSTIC TRANSMITTER SKETCH (REVISED)
//   ---------------------------------------
//   Clearer LED patterns to diagnose the state.
//   Using non-blocking transmit to avoid CPU freeze.

//   LED STATUS CODES:
//   -----------------
//   1. SOLID ON (First 1s)       -> Power On / Boot
//   2. SOS PATTERN (...---...)   -> Radio Init FAILED
//   3. SHORT BLIP (Every 2s)     -> Working! TX started successfully.
//   4. RAPID FLICKER (5 times)   -> TX Start Failed (Radio Busy/Error)
// */

// // LED Pin
// #ifndef RAD_LED
//   #define RAD_LED 37
// #endif

// // LoRa Pins (LilyGo T3S3 SX1280)
// #define LORA_SCK    5
// #define LORA_MISO   3
// #define LORA_MOSI   6
// #define LORA_CS     7
// #define LORA_RST    8
// #define LORA_DIO1   9
// #define LORA_BUSY   36

// // SX1280 radio = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);
// Module* radioModule = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);
// SX1280 radio(radioModule);

// // Globals
// volatile bool transmittedFlag = false;
// volatile bool enableInterrupt = true;
// unsigned long lastTxTime = 0;
// const unsigned long TX_INTERVAL = 2000; 
// int txCount = 0;

// // Interrupt Service Routine
// #if defined(ESP8266) || defined(ESP32)
//   ICACHE_RAM_ATTR
// #endif
// void setFlag(void) {
//   if(!enableInterrupt) return;
//   transmittedFlag = true;
// }

// void setup() {
//   pinMode(RAD_LED, OUTPUT);
//   Serial.begin(115200);
//   delay(3000); // Give time for the serial monitor to connect
//   Serial.println("\n--- Cabin Transmitter Booting ---");

//   // 1. BOOT: Steady ON for 1s
//   digitalWrite(RAD_LED, HIGH);
//   delay(1000); 
//   digitalWrite(RAD_LED, LOW);
//   delay(500);

//   // Init SPI
//   SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI);

//   // Init Radio with explicit parameters
//   Serial.print("[INFO] Initializing Radio... ");
  
//   // Assign RF Switch Control Pins (for PA/LNA)
//   #if defined(SX1280_RXEN) && defined(SX1280_TXEN)
//     radioModule->setRfSwitchPins(SX1280_RXEN, SX1280_TXEN);
//     Serial.print("(PA/LNA Enabled) ");
//   #endif

//   // Freq: 2400.0 MHz, BW: 406.25 kHz, SF: 7, CR: 5, Sync: 0x12, Pwr: 10dBm, Preamble: 12
//   int state = radio.begin(2400.0, 406.25, 7, 5, 0x12, 10, 12);

//   if (state == RADIOLIB_ERR_NONE) {
//     radio.setDio1Action(setFlag);
    
//     // Initial Transmit
//     // Serial.println("Init Success. Starting First TX...");
//     // radio.startTransmit("Hello Station!");
//     // digitalWrite(RAD_LED, HIGH); // ON during TX
//     // lastTxTime = millis();
//     Serial.println("Init Success. Waiting for Pi messages...");
//     lastTxTime = millis();
    
//   } else {
//     Serial.print("Init Failed, code ");
//     Serial.println(state);
//     while (true) {
//       // SOS Pattern Loop
//       // S (...)
//       for(int i=0; i<3; i++) { digitalWrite(RAD_LED, HIGH); delay(100); digitalWrite(RAD_LED, LOW); delay(100); }
//       delay(300);
//       // O (---)
//       for(int i=0; i<3; i++) { digitalWrite(RAD_LED, HIGH); delay(300); digitalWrite(RAD_LED, LOW); delay(100); }
//       delay(300);
//       // S (...)
//       for(int i=0; i<3; i++) { digitalWrite(RAD_LED, HIGH); delay(100); digitalWrite(RAD_LED, LOW); delay(100); }
//       delay(1000); 
//     }
//   }
// }

// void loop() {
//   // 1. CHECK INTERRUPT FLAG (Did previous TX finish?)
//   // if (transmittedFlag) {
//   //   // Reset flag safely
//   //   enableInterrupt = false;
//   //   transmittedFlag = false;
//   //   enableInterrupt = true;

//   //   // Turn OFF LED -> Successful TX end
//   //   digitalWrite(RAD_LED, LOW); 
//   //   Serial.println("TX Done");
//   // }
//   if (transmittedFlag) {
//   enableInterrupt = false;
//   transmittedFlag = false;
//   enableInterrupt = true;

//   int state = radio.finishTransmit();
//   Serial.print("TX Done, finishTransmit state=");
//   Serial.println(state);

//   txBusy = false;
//   digitalWrite(RAD_LED, LOW);
// }

//   // 2. CHECK SERIAL INPUT (From Raspberry Pi)
//   if (Serial.available()) {
//     String msg = Serial.readStringUntil('\n'); // Read until newline
//     msg.trim(); // Remove whitespace
//     Serial.print("SERIAL RX: [");
//     Serial.print(msg);
//     Serial.println("]");

//     if (msg.length() > 0) {
//       Serial.println("Sending: " + msg);
//       digitalWrite(RAD_LED, HIGH);

//       // Start Non-Blocking Transmit
//       // int state = radio.startTransmit(msg);

//       // if (state != RADIOLIB_ERR_NONE) {
//       //   Serial.print("TX Start Failed: ");
//       //   Serial.println(state);
//       //   digitalWrite(RAD_LED, LOW);
//       // }
//       if (!txBusy) {
//         int state = radio.startTransmit(msg);

//         if (state == RADIOLIB_ERR_NONE) {
//           txBusy = true;
//           lastTxTime = millis();
//         } else {
//           Serial.print("TX Start Failed: ");
//           Serial.println(state);
//           digitalWrite(RAD_LED, LOW);
//         }
//       } else {
//         Serial.println("TX BUSY - dropping incoming serial message");
//         digitalWrite(RAD_LED, LOW);
//       }
      
//       // Update timer to avoid conflicting with the heartbeat ping
//       lastTxTime = millis();
//     }
//   }

//   // 3. HEARTBEAT (Optional: Keep sending pings if idle for too long)
//   // Keeps the connection alive if the Pi stops sending data.
//   // if (millis() - lastTxTime > 10000) { // 10 seconds timeout
//   //   lastTxTime = millis();
    
//   //   // Payload
//   //   String msg = "Heartbeat " + String(txCount++);
//   //   Serial.println("Starting Heartbeat TX: " + msg);

//   //   // Turn ON LED -> Starting TX
//   //   digitalWrite(RAD_LED, HIGH);
    
//   //   // Start Non-Blocking Transmit
//   //   int state = radio.startTransmit(msg);
    
//   //   // Handle Immediate Start Failures
//   //   if (state != RADIOLIB_ERR_NONE) {
//   //     Serial.print("TX Start Failed: ");
//   //     Serial.println(state);
//   //     digitalWrite(RAD_LED, LOW); 
//   //   }
//   // }
// }


#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>

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

Module* radioModule = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);
SX1280 radio(radioModule);

// TX state
volatile bool transmittedFlag = false;
volatile bool enableInterrupt = true;
volatile bool txBusy = false;

#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void setFlag(void) {
  if (!enableInterrupt) return;
  transmittedFlag = true;
}

void setup() {
  pinMode(RAD_LED, OUTPUT);

  Serial.begin(115200);
  Serial.setTimeout(50);   // keep readStringUntil from blocking too long
  delay(3000);
  Serial.println("\n--- Cabin Transmitter Booting ---");

  // Boot LED
  digitalWrite(RAD_LED, HIGH);
  delay(1000);
  digitalWrite(RAD_LED, LOW);
  delay(300);

  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI);

  Serial.print("[INFO] Initializing Radio... ");

  #if defined(SX1280_RXEN) && defined(SX1280_TXEN)
    radioModule->setRfSwitchPins(SX1280_RXEN, SX1280_TXEN);
    Serial.print("(PA/LNA Enabled) ");
  #endif

  int state = radio.begin(2400.0, 406.25, 7, 5, 0x12, 10, 12);

  if (state == RADIOLIB_ERR_NONE) {
    radio.setDio1Action(setFlag);
    Serial.println("Init Success. Waiting for Pi messages...");
  } else {
    Serial.print("Init Failed, code ");
    Serial.println(state);

    while (true) {
      for (int i = 0; i < 3; i++) {
        digitalWrite(RAD_LED, HIGH); delay(100);
        digitalWrite(RAD_LED, LOW);  delay(100);
      }
      delay(300);
      for (int i = 0; i < 3; i++) {
        digitalWrite(RAD_LED, HIGH); delay(300);
        digitalWrite(RAD_LED, LOW);  delay(100);
      }
      delay(300);
      for (int i = 0; i < 3; i++) {
        digitalWrite(RAD_LED, HIGH); delay(100);
        digitalWrite(RAD_LED, LOW);  delay(100);
      }
      delay(1000);
    }
  }
}

void loop() {
  // finish previous TX
  if (transmittedFlag) {
    enableInterrupt = false;
    transmittedFlag = false;
    enableInterrupt = true;

    int state = radio.finishTransmit();
    Serial.print("TX Done, finishTransmit state=");
    Serial.println(state);

    txBusy = false;
    digitalWrite(RAD_LED, LOW);
  }

  // read ONE line from Raspberry Pi
  if (Serial.available()) {
    String msg = Serial.readStringUntil('\n');
    msg.trim();

    if (msg.length() > 0) {
      Serial.print("SERIAL RX: [");
      Serial.print(msg);
      Serial.println("]");

      if (!txBusy) {
        digitalWrite(RAD_LED, HIGH);

        int state = radio.startTransmit(msg);
        if (state == RADIOLIB_ERR_NONE) {
          txBusy = true;
          Serial.println("TX Start OK");
        } else {
          Serial.print("TX Start Failed: ");
          Serial.println(state);
          digitalWrite(RAD_LED, LOW);
        }
      } else {
        Serial.println("TX BUSY - dropping incoming serial message");
      }
    }
  }

  // Heartbeat disabled for debugging/stability
}