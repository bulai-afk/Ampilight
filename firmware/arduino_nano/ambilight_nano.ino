#include <Adafruit_NeoPixel.h>
#include "config.h"

// Пакет с компьютера: байт 'D', затем AMP_NUM_LEDS цветов RGB.
// Яркость считается в приложении.

Adafruit_NeoPixel strip(AMP_NUM_LEDS, AMP_DATA_PIN, AMP_ORDER + NEO_KHZ800);
static uint8_t colors[AMP_NUM_LEDS * 3];

void bootBlink() {
  for (int pass = 0; pass < 2; pass++) {
    for (int i = 0; i < AMP_NUM_LEDS; i++) {
      strip.setPixelColor(i, 36, 36, 36);
    }
    strip.show();
    delay(120);
    strip.clear();
    strip.show();
    delay(120);
  }
}

void flushLeftovers() {
  unsigned long quiet = millis();
  while (millis() - quiet < 4) {
    if (Serial.available() > 0) {
      Serial.read();
      quiet = millis();
    }
  }
}

void setup() {
  Serial.begin(115200);
  strip.begin();
  strip.clear();
  strip.show();
  bootBlink();
}

void loop() {
  if (Serial.available() <= 0 || Serial.read() != 'D') {
    return;
  }

  int got = 0;
  unsigned long started = millis();
  while (got < AMP_NUM_LEDS * 3 && millis() - started < 40) {
    while (Serial.available() > 0 && got < AMP_NUM_LEDS * 3) {
      colors[got++] = Serial.read();
    }
  }
  if (got < AMP_NUM_LEDS * 3) {
    flushLeftovers();
    return;
  }

  for (int i = 0; i < AMP_NUM_LEDS; i++) {
    strip.setPixelColor(i, colors[i * 3], colors[i * 3 + 1], colors[i * 3 + 2]);
  }
  strip.show();
}
