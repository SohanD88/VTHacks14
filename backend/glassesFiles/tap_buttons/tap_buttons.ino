/*
  tap_buttons.ino  v3  -  tap buttons / touch sensors for the bodycam pack.

  NEW IN v3: ANY button works, whichever way round it is wired.
    v2 only understood parts that rest LOW and go HIGH when touched (the Grove
    touch sensor). A push button that rests HIGH and goes LOW when pressed
    (Grove dual button, most button modules, a plain button wired from the pin
    to GND) showed D2=1 on the test page forever and never started a mission.
    v3 learns the resting level of each pin and sends the tap the moment the
    pin LEAVES that level. It also switches on the pin's built-in pull-up when
    nothing else is holding the pin, so a plain 2-leg button needs no resistor
    and an empty socket can no longer float and fire random taps. That is why
    both sockets are now on by default.

  YOUR BOARD IS AN ARDUINO UNO R4 WIFI. In the Arduino IDE:
    Tools > Board > Boards Manager > search "UNO R4" > install "Arduino UNO R4 Boards"
    Tools > Board > Arduino UNO R4 Boards > Arduino UNO R4 WiFi
    Tools > Port  > COM5
  Stop tap_stream.py (Ctrl+C) before you upload, or the upload fails.

  WIRING
    Grove shield: button / touch sensor 1 goes in the socket labeled D2.
                  (a second one goes in D3)
                  NOT the I2C, UART or A0 sockets.
    Loose wires, 3-pin module:    SIG -> pin 2, VCC -> 5V, GND -> GND.
    Loose wires, plain 2-leg button:  one leg -> pin 2, other leg -> GND.
                  (NOT to 5V. The pin rests at 5V, so it could never see the press.)

  The resting level is learned when the board boots and again every time
  tap_stream.py starts, so keep your fingers OFF the buttons at that moment.
  Plugged a button in later? Restart tap_stream.py or press RESET on the board.

  WHAT IT SENDS over USB at 9600 baud:
    READY v3     once, when the board boots
    INFO ...     notes for the tap_stream.py terminal (what each pin rests at)
    TAP1 / TAP2  the moment a button is pressed
    HB p2 p3 r2 r3 i2 i3    four times a second, for pins D2 and D3:
                 p = pressed at any time since the last heartbeat (1 = yes)
                 r = raw pin level right now,  i = the level the pin rests at
                 tap_stream.py shows these on the test page, so you can
                 watch D2 flip to 1 when you press the button.

  WHAT IT LISTENS FOR:
    L            learn the resting levels again (tap_stream.py sends this when it connects)

  The onboard LED (marked L) lights up for as long as a button is pressed.
*/

// Set to 1 to ignore socket D3 completely.
const int NUM_SENSORS = 2;

// Button on the other wire of the socket (Grove LED button)? Swap these: {3, 2}.
const int PINS[2] = {2, 3};
const char* NAMES[2] = {"TAP1", "TAP2"};

const unsigned long DEBOUNCE_MS = 400;   // ignore repeat taps faster than this
const int STABLE_READS = 3;              // this many equal reads in a row = real change

int restLevel[2] = {HIGH, HIGH};         // level of the pin when nobody is pressing
bool pressed[2] = {false, false};
bool pressedSinceBeat[2] = {false, false};
int changeCount[2] = {0, 0};
unsigned long lastTap[2] = {0, 0};
unsigned long lastBeat = 0;

// Find out what a pin rests at. With the pull-up on, a pin that STILL reads LOW is
// being held LOW by the part itself (touch sensor, Grove button). That part drives
// the line, so the pull-up goes back off. Everything else rests HIGH and keeps it.
void learnRest(int i) {
  pinMode(PINS[i], INPUT_PULLUP);
  delay(20);
  int highs = 0;
  for (int k = 0; k < 5; k++) {
    if (digitalRead(PINS[i]) == HIGH) highs++;
    delay(2);
  }
  restLevel[i] = highs >= 3 ? HIGH : LOW;
  if (restLevel[i] == LOW) pinMode(PINS[i], INPUT);
  pressed[i] = false;
  pressedSinceBeat[i] = false;
  changeCount[i] = 0;

  Serial.print("INFO D");
  Serial.print(PINS[i]);
  Serial.println(restLevel[i] == HIGH ? " rests HIGH, press = LOW" : " rests LOW, press = HIGH");
}

void setup() {
  Serial.begin(9600);
  pinMode(LED_BUILTIN, OUTPUT);
  delay(500);
  Serial.println("READY v3");
  for (int i = 0; i < 2; i++) learnRest(i);
}

void loop() {
  while (Serial.available() > 0) {
    if (Serial.read() == 'L') {
      for (int i = 0; i < 2; i++) learnRest(i);
    }
  }

  bool anyPressed = false;

  for (int i = 0; i < NUM_SENSORS; i++) {
    bool activeNow = digitalRead(PINS[i]) != restLevel[i];
    if (activeNow == pressed[i]) {
      changeCount[i] = 0;
    } else if (++changeCount[i] >= STABLE_READS) {   // same new level 3 reads in a row
      pressed[i] = activeNow;
      changeCount[i] = 0;
      if (pressed[i] && millis() - lastTap[i] > DEBOUNCE_MS) {
        Serial.println(NAMES[i]);                    // tap = the moment it is pressed
        lastTap[i] = millis();
      }
    }
    if (pressed[i]) {
      anyPressed = true;
      pressedSinceBeat[i] = true;
    }
  }

  digitalWrite(LED_BUILTIN, anyPressed ? HIGH : LOW);

  if (millis() - lastBeat >= 250) {            // heartbeat: pressed, raw level, resting level
    lastBeat = millis();
    Serial.print("HB ");
    Serial.print(pressedSinceBeat[0] ? 1 : 0);
    Serial.print(" ");
    Serial.print(pressedSinceBeat[1] ? 1 : 0);
    for (int i = 0; i < 2; i++) {
      Serial.print(" ");
      Serial.print(digitalRead(PINS[i]));
    }
    for (int i = 0; i < 2; i++) {
      Serial.print(" ");
      Serial.print(restLevel[i] == HIGH ? 1 : 0);
      pressedSinceBeat[i] = false;
    }
    Serial.println();
  }

  delay(10);
}
