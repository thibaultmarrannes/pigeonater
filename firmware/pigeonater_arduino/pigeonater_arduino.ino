#include <Servo.h>

const int RELAY_PIN = 7;
const int SERVO_PIN = 9;
const bool RELAY_ACTIVE_HIGH = true;
const long BAUD_RATE = 115200;

Servo deterrentServo;

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
  pinMode(RELAY_PIN, OUTPUT);
  setRelay(false);
  deterrentServo.attach(SERVO_PIN);
  deterrentServo.write(90);
  Serial.begin(BAUD_RATE);
  Serial.setTimeout(200);
}

void loop() {
  if (!Serial.available()) {
    return;
  }

  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) {
    return;
  }

  handleCommand(line);
}

void handleCommand(String line) {
  if (line == "PING") {
    Serial.println("OK PIGEONATER_ARDUINO v1");
    return;
  }

  if (line == "STATUS") {
    Serial.println("OK READY");
    return;
  }

  if (line.startsWith("LED_BLINK ")) {
    int firstSpace = line.indexOf(' ');
    int secondSpace = line.indexOf(' ', firstSpace + 1);
    if (firstSpace < 0 || secondSpace < 0) {
      Serial.println("ERR INVALID_LED_BLINK");
      return;
    }

    int count = line.substring(firstSpace + 1, secondSpace).toInt();
    int blinkMs = line.substring(secondSpace + 1).toInt();
    if (count < 1 || count > 20 || blinkMs < 20 || blinkMs > 2000) {
      Serial.println("ERR INVALID_LED_BLINK");
      return;
    }

    for (int i = 0; i < count; i++) {
      digitalWrite(LED_BUILTIN, HIGH);
      delay(blinkMs);
      digitalWrite(LED_BUILTIN, LOW);
      delay(blinkMs);
    }
    Serial.println("OK LED_BLINK");
    return;
  }

  if (line.startsWith("RELAY_PULSE ")) {
    int pulseMs = line.substring(12).toInt();
    if (pulseMs < 50 || pulseMs > 10000) {
      Serial.println("ERR INVALID_RELAY_PULSE");
      return;
    }
    setRelay(true);
    delay(pulseMs);
    setRelay(false);
    Serial.println("OK RELAY_PULSE");
    return;
  }

  if (line.startsWith("SERVO_WRITE ")) {
    int angle = line.substring(12).toInt();
    if (!validAngle(angle)) {
      Serial.println("ERR INVALID_SERVO_ANGLE");
      return;
    }
    deterrentServo.write(angle);
    Serial.println("OK SERVO_WRITE");
    return;
  }

  if (line.startsWith("SERVO_SWEEP ")) {
    int firstSpace = line.indexOf(' ');
    int secondSpace = line.indexOf(' ', firstSpace + 1);
    int thirdSpace = line.indexOf(' ', secondSpace + 1);
    if (firstSpace < 0 || secondSpace < 0 || thirdSpace < 0) {
      Serial.println("ERR INVALID_SERVO_SWEEP");
      return;
    }

    int fromAngle = line.substring(firstSpace + 1, secondSpace).toInt();
    int toAngle = line.substring(secondSpace + 1, thirdSpace).toInt();
    int stepDelayMs = line.substring(thirdSpace + 1).toInt();
    if (!validAngle(fromAngle) || !validAngle(toAngle) || stepDelayMs < 1 || stepDelayMs > 1000) {
      Serial.println("ERR INVALID_SERVO_SWEEP");
      return;
    }

    int step = fromAngle <= toAngle ? 1 : -1;
    for (int angle = fromAngle; angle != toAngle; angle += step) {
      deterrentServo.write(angle);
      delay(stepDelayMs);
    }
    deterrentServo.write(toAngle);
    Serial.println("OK SERVO_SWEEP");
    return;
  }

  Serial.println("ERR UNKNOWN_COMMAND");
}

void setRelay(bool enabled) {
  int active = RELAY_ACTIVE_HIGH ? HIGH : LOW;
  int inactive = RELAY_ACTIVE_HIGH ? LOW : HIGH;
  digitalWrite(RELAY_PIN, enabled ? active : inactive);
}

bool validAngle(int angle) {
  return angle >= 0 && angle <= 180;
}
