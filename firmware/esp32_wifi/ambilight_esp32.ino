#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_wifi.h>
#include <ArduinoOTA.h>
#include <Adafruit_NeoPixel.h>
#include "config.h"

// Тот же пакет, что и у Nano: 'D' + RGB на каждый диод.
// Приходит по Wi-Fi (UDP) или по USB.
// На запрос "AMP?" плата отвечает "AMP,<ip>,<число диодов>".
// Ещё плата понимает DDP (порт 4048, RGB) — его шлют WLED-совместимые программы.

#define DDP_PORT 4048
#define DDP_FLAG_TIMECODE 0x10
#define DDP_FLAG_PUSH 0x01

Adafruit_NeoPixel strip(AMP_NUM_LEDS, AMP_DATA_PIN, AMP_ORDER + NEO_KHZ800);
WiFiUDP udp;
WiFiUDP ddp;
static uint8_t packet[1 + AMP_NUM_LEDS * 3];
static uint8_t serialColors[AMP_NUM_LEDS * 3];
static uint8_t ddpPacket[1500];
static uint8_t ddpColors[AMP_NUM_LEDS * 3];
bool wifiReady = false;
bool otaReady = false;

void startOta() {
  if (otaReady) return;
  ArduinoOTA.setHostname("ampilight");
  ArduinoOTA.setPassword(AMP_WIFI_PASS);
  ArduinoOTA.setPort(3232);
  ArduinoOTA.onStart([]() {
    strip.clear();
    strip.show();
  });
  ArduinoOTA.begin();
  otaReady = true;
}

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

void showColors(const uint8_t *rgb) {
  for (int i = 0; i < AMP_NUM_LEDS; i++) {
    strip.setPixelColor(i, rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2]);
  }
  strip.show();
}

void replyDiscovery() {
  IPAddress ip = WiFi.localIP();
  char reply[48];
  snprintf(reply, sizeof(reply), "AMP,%u.%u.%u.%u,%d", ip[0], ip[1], ip[2], ip[3], AMP_NUM_LEDS);
  udp.beginPacket(udp.remoteIP(), udp.remotePort());
  udp.print(reply);
  udp.endPacket();
}

// Заголовок DDP: флаги, номер, тип, id, смещение (4 байта), длина (2 байта),
// при флаге timecode ещё 4 байта. Дальше RGB с указанного смещения.
void handleDdp() {
  int size = ddp.parsePacket();
  if (size <= 0) return;
  int length = ddp.read(ddpPacket, sizeof(ddpPacket));
  if (length < 10) return;
  uint8_t flags = ddpPacket[0];
  int header = (flags & DDP_FLAG_TIMECODE) ? 14 : 10;
  if (length < header) return;
  uint32_t offset = ((uint32_t)ddpPacket[4] << 24) | ((uint32_t)ddpPacket[5] << 16)
                    | ((uint32_t)ddpPacket[6] << 8) | ddpPacket[7];
  int dataLength = (ddpPacket[8] << 8) | ddpPacket[9];
  dataLength = min(dataLength, length - header);
  const int total = AMP_NUM_LEDS * 3;
  if (offset < (uint32_t)total && dataLength > 0) {
    int count = min(dataLength, total - (int)offset);
    memcpy(ddpColors + offset, ddpPacket + header, count);
  }
  if (flags & DDP_FLAG_PUSH) showColors(ddpColors);
}

void setup() {
  Serial.begin(115200);
  strip.begin();
  strip.clear();
  strip.show();
  bootBlink();

  WiFi.setHostname("ampilight");
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(true);
  // Каналы 12 и 13. Без этого плата не видит сеть, если роутер сидит выше 11-го канала.
  wifi_country_t country = {};
  memcpy(country.cc, "01", 3);
  country.schan = 1;
  country.nchan = 13;
  country.policy = WIFI_COUNTRY_POLICY_MANUAL;
  esp_wifi_set_country(&country);
  WiFi.begin(AMP_WIFI_SSID, AMP_WIFI_PASS);
  unsigned long started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < 20000) {
    delay(200);
  }
  if (WiFi.status() == WL_CONNECTED) {
    udp.begin(AMP_UDP_PORT);
    ddp.begin(DDP_PORT);
    startOta();
    wifiReady = true;
    Serial.print("AMPILIGHT ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.print("AMPILIGHT NOWIFI ");
    Serial.println(WiFi.status());
  }
}

void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    if (!wifiReady) {
      udp.begin(AMP_UDP_PORT);
      ddp.begin(DDP_PORT);
      startOta();
      wifiReady = true;
      Serial.print("AMPILIGHT ");
      Serial.println(WiFi.localIP());
    }
    int size = udp.parsePacket();
    if (size > 0) {
      int length = udp.read(packet, sizeof(packet));
      if (length == 4 && packet[0] == 'A' && packet[1] == 'M' && packet[2] == 'P' && packet[3] == '?') {
        replyDiscovery();
      } else if (length >= 1 + AMP_NUM_LEDS * 3 && packet[0] == 'D') {
        showColors(packet + 1);
      }
    }
    handleDdp();
    ArduinoOTA.handle();
  } else {
    wifiReady = false;
    otaReady = false;
    static unsigned long lastTry = 0;
    if (millis() - lastTry > 5000) {
      lastTry = millis();
      WiFi.reconnect();
    }
  }

  if (Serial.available() > 0 && Serial.read() == 'D') {
    int got = 0;
    unsigned long started = millis();
    while (got < AMP_NUM_LEDS * 3 && millis() - started < 40) {
      while (Serial.available() > 0 && got < AMP_NUM_LEDS * 3) {
        serialColors[got++] = Serial.read();
      }
    }
    if (got == AMP_NUM_LEDS * 3) {
      showColors(serialColors);
    }
  }
}
