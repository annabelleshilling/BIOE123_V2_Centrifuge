/*
 * Motor On/Off UI Test
 *
 * Minimal Arduino script that speaks the same serial protocol
 * as the full centrifuge code, but only implements ON and OFF.
 * No PID, no tachometer, no safety checks, no state machine.
 *
 * Hardware:
 * - D5 : PWM output to MOSFET gate
 *
 * The UI sends START:<RPM>:<DURATION_MS> to turn on
 * and STOP to turn off. This script ignores RPM and duration
 * and just toggles the motor at a fixed PWM.
 *
 * Adjust MOTOR_SPEED (0-255) to set run speed.
 */

const int MOTOR_PWM_PIN = 5;
const int MOTOR_SPEED   = 128;  // adjust as needed

String serialBuffer = "";
bool   motorOn      = false;

unsigned long lastStatusTime = 0;
const unsigned long STATUS_INTERVAL = 200;  // match UI polling rate

void setup() {
  Serial.begin(115200);
  pinMode(MOTOR_PWM_PIN, OUTPUT);
  analogWrite(MOTOR_PWM_PIN, 0);
  Serial.println("System Ready");
}

void loop() {
  // Read serial commands
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n') {
      serialBuffer.trim();
      processCommand(serialBuffer);
      serialBuffer = "";
    } else {
      serialBuffer += c;
    }
  }

  // Send status update so the UI stays happy
  if (millis() - lastStatusTime >= STATUS_INTERVAL) {
    sendStatus();
    lastStatusTime = millis();
  }
}

void processCommand(String cmd) {
  if (cmd.startsWith("START:")) {
    analogWrite(MOTOR_PWM_PIN, MOTOR_SPEED);
    motorOn = true;
    Serial.println("ACK:START");
    Serial.println("STATE:RUNNING");

  } else if (cmd == "STOP") {
    analogWrite(MOTOR_PWM_PIN, 0);
    motorOn = false;
    Serial.println("ACK:STOP");
    Serial.println("STATE:IDLE");

  } else if (cmd == "PING") {
    Serial.println("PONG");

  } else if (cmd == "STATUS") {
    sendStatus();

  } else if (cmd == "CLEAR_ERROR") {
    Serial.println("ACK:CLEAR_ERROR");

  } else {
    Serial.print("ERROR:UNKNOWN_COMMAND:");
    Serial.println(cmd);
  }
}

void sendStatus() {
  Serial.print("{\"state\":\"");
  Serial.print(motorOn ? "RUNNING" : "IDLE");
  Serial.print("\",\"currentRPM\":0,\"targetRPM\":0,\"pwm\":");
  Serial.print(motorOn ? MOTOR_SPEED : 0);
  Serial.print(",\"running\":");
  Serial.print(motorOn ? "true" : "false");
  Serial.println("}");
}
