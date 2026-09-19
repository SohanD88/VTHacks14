/*
  tap_buttons.ino  v2  -  touch sensor taps for the bodycam pack.

  YOUR BOARD IS AN ARDUINO UNO R4 WIFI. In the Arduino IDE:
    Tools > Board > Boards Manager > search "UNO R4" > install "Arduino UNO R4 Boards"
    Tools > Board > Arduino UNO R4 Boards > Arduino UNO R4 WiFi
    Tools > Port  > COM5
  Stop tap_stream.py (Ctrl+C) before you upload, or the upload fails.

  WIRING
    Grove shield: touch sensor 1 goes in the socket labeled D2.
                  (a second sensor goes in D3)
                  NOT the I2C, UART or A0 sockets.
    Loose wires:  yellow (SIG) -> pin 2, red (VCC) -> 5V, black (GND) -> GND.

  WHAT IT SENDS over USB at 9600 baud:
    READY        once, when the board boots
    TAP1 / TAP2  when a sensor is tapped
    HB 0 0       four times a second: the live state of pins D2 and D3.
                 tap_stream.py shows these on the test page, so you can
                 watch D2 flip to 1 when you touch the pad.

  The onboard LED (marked L) lights up for as long as a pad is touched.
*/

// Only one sensor plugged in? Leave this at 1. An empty D3 socket floats and
// would fire random hazard markers. Change to 2 when the second sensor is in D3.
const int NUM_SENSORS = 1;

const int PINS[2] = {2, 3};
const char* NAMES[2] = {"TAP1", "TAP2"};

const unsigned long DEBOUNCE_MS = 400;   // ignore repeat taps faster than this
const int STABLE_READS = 3;              // HIGH this many reads in a row = real touch

int highCount[2] = {0, 0};
bool wasTouched[2] = {false, false};
unsigned long lastTap[2] = {0, 0};
unsigned long lastBeat = 0;

void setup() {
  Serial.begin(9600);
  for (int i = 0; i < 2; i++) pinMode(PINS[i], INPUT);
  pinMode(LED_BUILTIN, OUTPUT);
  delay(500);
  Serial.println("READY");
}

void loop() {
  bool anyTouched = false;

  for (int i = 0; i < NUM_SENSORS; i++) {
    if (digitalRead(PINS[i]) == HIGH) {        // Grove touch sensor = HIGH when touched
      if (highCount[i] < STABLE_READS) highCount[i]++;
    } else {
      highCount[i] = 0;
    }
    bool touched = highCount[i] >= STABLE_READS;
    if (touched) anyTouched = true;

    if (touched && !wasTouched[i] && millis() - lastTap[i] > DEBOUNCE_MS) {
      Serial.println(NAMES[i]);
      lastTap[i] = millis();
    }
    wasTouched[i] = touched;
  }

  digitalWrite(LED_BUILTIN, anyTouched ? HIGH : LOW);

  if (millis() - lastBeat >= 250) {            // heartbeat with live pin states
    lastBeat = millis();
    Serial.print("HB ");
    Serial.print(digitalRead(PINS[0]));
    Serial.print(" ");
    Serial.println(digitalRead(PINS[1]));
  }

  delay(10);
}
