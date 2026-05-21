# =============================================================================
# main.py  —  MicroPython, runs on the ESP32
#
# Reads ADS1220 via SPI and streams JSON lines over USB Serial.
# Output format: {"voltage": 12.3456}
#
# WIRING:
#   ADS1220 DRDY  → GPIO  4
#   ADS1220 MISO  → GPIO 19
#   ADS1220 MOSI  → GPIO 23
#   ADS1220 SCLK  → GPIO 18
#   ADS1220 CS    → GPIO  5
#   ADS1220 DVDD + AVDD → 3.3V
#   ADS1220 DGND + AGND → GND
#   ADS1220 AIN0  → Node A (front-end signal)
#   ADS1220 AIN1  → 1.65V midpoint
# =============================================================================

import time
import json
from machine import SPI, Pin

# ── Pin assignments ───────────────────────────────────────────────────────────
PIN_SCK  = 18
PIN_MOSI = 23
PIN_MISO = 19
PIN_CS   = 5
PIN_DRDY = 4

# ── ADS1220 scaling ───────────────────────────────────────────────────────────
VREF         = 2.048   # Internal reference voltage (V)
GAIN         = 1
ADC_COUNTS   = 2**23   # 24-bit signed full scale
SCALE_FACTOR = 151     # V_BNC = V_diff x 151

# ── Calibration ───────────────────────────────────────────────────────────────
CAL_M = 0.6662458  # Gain multiplier (slope)
CAL_B = -160.7800  # Zero offset in Volts

# ── ADS1220 commands ──────────────────────────────────────────────────────────
CMD_RESET = 0x06
CMD_START = 0x08
CMD_RDATA = 0x10

# ── Config registers ──────────────────────────────────────────────────────────
# Reg 0: MUX=0001 (AIN0+/AIN1-), GAIN=000 (x1), PGA_BYPASS=0  → 0x10
# Reg 1: DR=000 (20 SPS, best noise rejection), single-shot    → 0x00
# Reg 2: VREF=00 (internal 2.048V), FIR=10 (50Hz rejection)   → 0x08
#        Change to 0x0C for 60Hz mains rejection
# Reg 3: all defaults                                          → 0x00
ADS_CONFIG = bytes([0x10, 0x00, 0x08, 0x00])


class ADS1220:

    def __init__(self):
        self.spi = SPI(
            1,
            baudrate=1_000_000,
            polarity=0,
            phase=1,
            sck=Pin(PIN_SCK),
            mosi=Pin(PIN_MOSI),
            miso=Pin(PIN_MISO)
        )
        self.cs   = Pin(PIN_CS,   Pin.OUT, value=1)  # CS idles high
        self.drdy = Pin(PIN_DRDY, Pin.IN)
        self._reset()
        self._configure()

    def _send(self, data):
        self.cs.value(0)
        self.spi.write(bytes(data))
        self.cs.value(1)

    def _reset(self):
        self._send([CMD_RESET])
        time.sleep_ms(2)

    def _configure(self):
        # WREG: 0x40 | (reg0 << 2) | (4 regs - 1) = 0x43
        self._send([0x43] + list(ADS_CONFIG))

    def _wait_drdy(self, timeout_ms=500):
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        while self.drdy.value() == 1:
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                raise RuntimeError("DRDY timeout - check wiring")
            time.sleep_us(100)

    def read_raw(self):
        self._send([CMD_START])
        self._wait_drdy()

        rx = bytearray(4)
        tx = bytes([CMD_RDATA, 0x00, 0x00, 0x00])
        self.cs.value(0)
        self.spi.write_readinto(tx, rx)
        self.cs.value(1)

        # rx[0] is command echo, rx[1:4] are the data bytes
        unsigned = (rx[1] << 16) | (rx[2] << 8) | rx[3]
        # Sign-extend from 24-bit to Python int
        if unsigned & 0x800000:
            signed = unsigned - 0x1000000
        else:
            signed = unsigned
        return signed

    def read_voltage(self):
        raw = self.read_raw()
        v_diff = (raw / ADC_COUNTS) * (VREF / GAIN)
        v_raw_bnc = v_diff * SCALE_FACTOR

        # Apply two-point linear calibration
        v_calibrated = (v_raw_bnc * CAL_M) + CAL_B

        return round(v_calibrated, 4)


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    adc = ADS1220()

    while True:
        try:
            voltage = adc.read_voltage()
            print(json.dumps({"voltage": voltage}))
        except Exception as e:
            print(json.dumps({"voltage": None, "error": str(e)}))
        time.sleep_ms(200)  # 5 readings per second


main()