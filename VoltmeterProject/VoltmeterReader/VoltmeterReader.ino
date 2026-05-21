// =============================================================================
// ads1220_reader.ino  —  Upload via Arduino IDE to ESP32 DevKitC
//
// ARDUINO IDE SETUP (one-time):
//   1. File → Preferences → Additional Boards Manager URLs, add:
//      https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
//   2. Tools → Board → Boards Manager → search "esp32" → install "esp32 by Espressif Systems"
//   3. Tools → Board → ESP32 Arduino → "ESP32 Dev Module"
//   4. Tools → Port → select your ESP32 COM port
//   5. Upload this sketch
//
// WIRING (ADS1220 breakout → ESP32):
//   DRDY  → GPIO  4
//   MISO  → GPIO 19
//   MOSI  → GPIO 23
//   SCLK  → GPIO 18
//   CS    → GPIO  5
//   CLK   → Leave unconnected
//   DVDD  → 3.3V
//   DGND  → GND
//   AIN0  → Node A (signal from front-end)
//   AIN1  → 1.65V midpoint node
//   AVDD  → 3.3V
//   AGND  → GND
//   REFP0, REFN0, AIN2, AIN3 → Leave unconnected
// =============================================================================

#include <SPI.h>

// ── Pin definitions ───────────────────────────────────────────────────────────
#define PIN_CS    5
#define PIN_DRDY  4
// SCK=18, MISO=19, MOSI=23 used automatically by the ESP32 VSPI bus

// ── ADS1220 commands ──────────────────────────────────────────────────────────
#define CMD_RESET  0x06
#define CMD_START  0x08
#define CMD_RDATA  0x10
#define CMD_WREG   0x40

// ── Config register values ────────────────────────────────────────────────────
// Reg 0: MUX=0001 (AIN0+/AIN1-), GAIN=000 (x1), PGA_BYPASS=0  → 0x10
// Reg 1: DR=000 (20 SPS), MODE=00, CM=0 (single-shot), TS=0    → 0x00
// Reg 2: VREF=00 (internal 2.048V), FIR=10 (50Hz rejection)    → 0x08
//        Change to 0x0C for 60Hz rejection
// Reg 3: all defaults                                           → 0x00
const uint8_t ADS_CONFIG[4] = { 0x10, 0x00, 0x08, 0x00 };

// ── Scaling constants ─────────────────────────────────────────────────────────
const float VREF          = 2.048f;
const float GAIN          = 1.0f;
const long  ADC_FULLSCALE = 8388608L;  // 2^23
const float SCALE_FACTOR  = 151.0f;   // V_BNC = V_diff x 151

SPIClass vspi(VSPI);

// ── SPI helpers ───────────────────────────────────────────────────────────────

void ads_cs_low()  { digitalWrite(PIN_CS, LOW);  }
void ads_cs_high() { digitalWrite(PIN_CS, HIGH); }

void ads_send_byte(uint8_t b) {
  ads_cs_low();
  vspi.transfer(b);
  ads_cs_high();
}

void ads_reset() {
  ads_send_byte(CMD_RESET);
  delay(2);
}

void ads_configure() {
  // WREG: 0x40 | (reg0 << 2) | (4 regs - 1) = 0x43
  ads_cs_low();
  vspi.transfer(0x43);
  vspi.transfer(ADS_CONFIG[0]);
  vspi.transfer(ADS_CONFIG[1]);
  vspi.transfer(ADS_CONFIG[2]);
  vspi.transfer(ADS_CONFIG[3]);
  ads_cs_high();
}

bool ads_wait_drdy(uint32_t timeout_ms = 500) {
  uint32_t start = millis();
  while (digitalRead(PIN_DRDY) == HIGH) {
    if ((millis() - start) > timeout_ms) return false;
    delayMicroseconds(100);
  }
  return true;
}

long ads_read_raw() {
  ads_send_byte(CMD_START);
  if (!ads_wait_drdy()) return LONG_MIN;

  ads_cs_low();
  vspi.transfer(CMD_RDATA);
  uint8_t b0 = vspi.transfer(0x00);
  uint8_t b1 = vspi.transfer(0x00);
  uint8_t b2 = vspi.transfer(0x00);
  ads_cs_high();

  long raw = ((long)b0 << 16) | ((long)b1 << 8) | (long)b2;
  if (raw & 0x800000L) raw |= 0xFF000000L;  // sign-extend
  return raw;
}

float ads_read_voltage() {
  long raw = ads_read_raw();
  if (raw == LONG_MIN) return NAN;
  float v_diff = ((float)raw / (float)ADC_FULLSCALE) * (VREF / GAIN);
  return v_diff * SCALE_FACTOR;
}

// ── Setup / Loop ──────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  while (!Serial) { delay(10); }

  pinMode(PIN_CS,   OUTPUT);
  pinMode(PIN_DRDY, INPUT);
  digitalWrite(PIN_CS, HIGH);

  vspi.begin(18, 19, 23, PIN_CS);  // SCK, MISO, MOSI, SS
  vspi.setDataMode(SPI_MODE1);
  vspi.setFrequency(1000000);

  ads_reset();
  ads_configure();

  Serial.println("{\"status\":\"ADS1220 ready\"}");
}

void loop() {
  float voltage = ads_read_voltage();

  if (isnan(voltage)) {
    Serial.println("{\"voltage\":null,\"error\":\"DRDY timeout - check wiring\"}");
  } else {
    Serial.print("{\"voltage\":");
    Serial.print(voltage, 4);
    Serial.println("}");
  }

  delay(200);  // 5 readings per second
}
