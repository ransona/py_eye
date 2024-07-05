const int outputPin = 8; // The pin number for the digital output
bool pinState = LOW;     // Initial state of the digital output

void setup() {
  pinMode(outputPin, OUTPUT); // Set the pin as an output
  digitalWrite(outputPin, pinState); // Initialize the pin state
  Serial.begin(9600);         // Start the serial communication at 9600 baud rate
}

void loop() {
  if (Serial.available() > 0) {
    char command = Serial.read(); // Read the incoming byte

    if (command == 'T') {
      // Toggle the pin state
      pinState = !pinState;
      digitalWrite(outputPin, pinState);
    } else if (command == 'H') {
      // Set the pin high
      pinState = HIGH;
      digitalWrite(outputPin, pinState);
    } else if (command == 'L') {
      // Set the pin low
      pinState = LOW;
      digitalWrite(outputPin, pinState);
    }
  }
}