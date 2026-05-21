# Port Sniffing, Decibel, & Protocols Notes

---

# 1. Understanding the Decibel

## Core Formula

|Quantity|Formula|
|---|---|
|Power ratio|`L = 10 · log₁₀(P / P₀)`|
|Amplitude/voltage ratio|`L = 20 · log₁₀(A / A₀)`|

> **Why 20 for amplitude?** Because P ∝ V², so 10·log(V²/V₀²) = 20·log(V/V₀).  
> **Key insight:** Cascaded gains _multiply_ in linear but _add_ in dB.

## Must-Memorize Values

|dB|Power ratio|Voltage ratio|Intuition|
|---|---|---|---|
|+3|×2|×1.414|Double power|
|+6|×4|×2|Double voltage|
|+10|×10|×3.162|One decade (power)|
|+20|×100|×10|One decade (voltage)|
|0|×1|×1|Equal to reference|
|−3|×0.5|×0.707|Half power (filter BW)|
|−10|×0.1|×0.316|One decade down|

**Combo rule:** 13 dB = 10+3 → ×10 × ×2 = ×20

## The −3 dB Point

Appears everywhere: filter bandwidth, scope bandwidth, antenna HPBW, resonant Q, amplifier corner frequency.  
A "100 MHz scope" is −3 dB _at_ 100 MHz — not a brick wall.

---

## Absolute dB Units (the suffix = the reference)

|Unit|Reference|Formula|Typical Use|
|---|---|---|---|
|**dBm**|1 mW|10·log(P/1mW)|RF, microwave, fiber|
|**dBW**|1 W|10·log(P/1W)|Radar, broadcast|
|**dBV**|1 V rms|20·log(V/1V)|Consumer audio, scopes|
|**dBu**|0.7746 V rms|20·log(V/0.7746)|Pro audio, broadcast|
|**dBμV**|1 μV rms|20·log(V/1μV)|RF receivers, EMC|
|**dB SPL**|20 μPa|20·log(p/20μPa)|Acoustics|
|**dBFS**|ADC full scale|20·log(\|x\|/xmax)|Digital audio (always ≤ 0)|
|**dBc**|Carrier power|10·log(P/P_carrier)|Spurs, phase noise|
|**dBi**|Isotropic antenna|—|Antenna gain|
|**dBd**|Half-wave dipole|dBi − 2.15|VHF/UHF antennas|

### Key Conversions

- `dBm = dBW + 30`
- `dBμV (50Ω) = dBm + 107`
- `dBV = dBu − 2.22`
- `dBi = dBd + 2.15`
- `EIRP = TX power (dBm) + antenna gain (dBi)`

### Notable Anchors

- Wi-Fi TX: +20 dBm (100 mW)
- Receiver noise floor: −174 dBm/Hz (290 K)
- Pro audio line level: +4 dBu = 1.228 V
- Consumer audio: −10 dBV = 316 mV → **~12 dB mismatch** vs pro gear

### dBFS Notes

- Values are always **≤ 0** (positive = clipping)
- 16-bit SNR ≈ 98 dB; 24-bit ≈ 146 dB
- 0 dBFS → typically +24 dBu (pro DAC)

---

## Common Pitfalls

- **10 vs 20 log** — wrong choice = factor-of-2 error
- **Impedance** — dBμV → dBm only valid at known R (50 Ω RF, 75 Ω video)
- **RMS vs peak** — peak = RMS × √2 ≈ +3 dB
- **Noise bandwidth** — −174 dBm is _per Hz_; add 10·log(BW) for real bandwidth
- **dBd vs dBi** — always convert to dBi before link budget math

## RF Link Budget Example

```
TX +20 dBm → cable −2 dB → TX antenna +8 dBi → path loss −70 dB → RX antenna +3 dBi
= +20 − 2 + 8 − 70 + 3 = −41 dBm ≈ 79 nW
Wi-Fi sensitivity ~−90 dBm → 49 dB link margin ✓
```

---

# 2. Communication Protocols

## Serial Fundamentals

- **Synchronous** — shared clock (SPI, I²C, USB internally)
- **Asynchronous** — pre-agreed baud rate, start/stop bits (UART, RS-232)
- **Duplex:** Simplex (1-way) / Half-duplex (alternating) / Full-duplex (simultaneous)
- **Baud ≠ bit rate** when M > 2 symbols; for binary (UART): bps = baud

---

## Signal Standards

|Standard|Logic 0|Logic 1|Max Speed|Distance|
|---|---|---|---|---|
|TTL|+2.4–5 V|0–0.8 V|1 Mbps|~1 m PCB|
|CMOS 3.3V|+2.0–3.3 V|0–0.8 V|100 Mbps|~1 m PCB|
|RS-232|+3 to +15 V|−3 to −15 V|20 kbps std|≤ 15 m|
|RS-485|Diff ≥ +200 mV|Diff ≤ −200 mV|10 Mbps|≤ 1200 m|
|CAN bus|Dominant 2.5 V|Recessive 3.5 V|1 Mbps|≤ 1000 m|

> ⚠️ **RS-232 inverted logic** — Logic 1 = NEGATIVE voltage (MARK). Trips up everyone.

---

## RS-232 / UART

### UART Frame (8N1)

`IDLE (HIGH) → START (LOW, 1 bit) → D0–D7 (LSB first) → [PARITY] → STOP (HIGH) → IDLE`

- **8N1** = 8 data bits, No parity, 1 stop bit — most common
- At 9600 bps: 10 bits/byte → ~961 bytes/sec
- At 115200 bps: ~11,520 bytes/sec
- Common lab rates: **9600 and 115200**

### DB-9 Pinout (DTE side)

|Pin|Signal|Direction|
|---|---|---|
|1|DCD — Data Carrier Detect|DCE→DTE|
|2|RXD — Receive Data|DCE→DTE|
|3|TXD — Transmit Data|DTE→DCE|
|4|DTR — Data Terminal Ready|DTE→DCE|
|5|GND|common|
|6|DSR — Data Set Ready|DCE→DTE|
|7|RTS — Request To Send|DTE→DCE|
|8|CTS — Clear To Send|DCE→DTE|
|9|RI — Ring Indicator|DCE→DTE|

**Null modem (DTE-DTE):** Cross TXD↔RXD, RTS↔CTS, DTR↔DSR. GND straight-through.

---

## SPI vs I²C

|Feature|SPI|I²C|
|---|---|---|
|Wires|4 (SCLK, MOSI, MISO, CS)|2 (SDA, SCL) — open-drain + pull-up|
|Speed|50+ MHz|100k / 400k / 1M / 3.4M bps|
|Addressing|CS pin per slave|7-bit address (up to 127 devices)|
|Duplex|Full|Half|
|Use|Flash, ADC, displays|Sensors, EEPROMs, OLEDs|

**I²C pull-up:** ~4.7 kΩ @ 100 kbps, ~2.2 kΩ @ 400 kbps

---

## USB Versions

|Version|Speed|Notes|
|---|---|---|
|USB 2.0|480 Mbps|NRZI encoding; universal HID/MSC/CDC|
|USB 3.0|5 Gbps|8b/10b (20% overhead); blue insert|
|USB 3.2 G2×2|20 Gbps|Dual-lane, 128b/132b (3% overhead)|
|USB4 v1|40 Gbps|Type-C only|
|USB4 v2|80 Gbps|PAM-2; up to 240 W (USB-PD 3.1 EPR)|

### USB Power Delivery

|Standard|V_max|P_max|
|---|---|---|
|USB 2.0|5 V|2.5 W|
|USB 3.x|5 V|4.5 W|
|USB-PD 1.0|20 V|100 W|
|USB-PD 3.1 EPR|48 V|240 W|

> USB-C cables must be **e-marked** for ≥3 A or any USB-PD profile.

### USB-C Alternate Modes

DisplayPort (up to 8K), Thunderbolt 3/4 (40 Gbps, daisy-chain 6 devices), HDMI Alt Mode, MHL

---

## Bluetooth

|Version|Key Feature|
|---|---|
|1.0 (1999)|1 Mbps, 79 channels|
|2.0 (2004)|EDR — 3 Mbps|
|4.0 (2010)|**BLE introduced**|
|5.0 (2016)|4× range, 2× speed BLE, 8× broadcast|
|5.1 (2019)|AoA/AoD direction finding (cm accuracy)|
|5.2 (2020)|LE Audio (LC3 codec)|
|**6.0 (2024)**|Channel Sounding (HADM) — sub-decimeter ranging|

**Classic BR/EDR:** 79 ch @ 1 MHz, FHSS 1600 hops/sec, piconet (1 master + 7 slaves). Use: audio, HID.  
**BLE:** 40 channels (37–39 = advertising), 1–2 Mbps, 0.01–0.5 mW. Use: IoT, wearables. Stack: GATT/ATT/GAP.

---

## TCP/IP & Networking

### OSI → TCP/IP Mapping

```
OSI L7/L6/L5 (Application/Presentation/Session) → TCP/IP Application (HTTP, DNS, SSH)
OSI L4 (Transport)                               → TCP/IP Transport (TCP, UDP)
OSI L3 (Network)                                 → TCP/IP Internet (IP, ICMP)
OSI L2/L1 (Data Link/Physical)                  → TCP/IP Network Access (Ethernet, Wi-Fi)
```

### TCP vs UDP

||TCP|UDP|
|---|---|---|
|Connection|3-way handshake|Connectionless|
|Reliability|Guaranteed, ordered|Best effort|
|Header|20–60 bytes|8 bytes (fixed)|
|Use|HTTP, SSH, FTP|DNS, VoIP, video|

### Key Protocols & Ports

|Protocol|Port|Purpose|
|---|---|---|
|HTTP|80|Web|
|HTTPS|443|Encrypted web|
|SSH|22|Encrypted terminal|
|DNS|53|Name resolution|
|DHCP|67/68|Auto IP assignment|

### IP Addressing

- **IPv4:** 32-bit; ~4.3B addresses; exhausted 2011, extended via NAT
- **IPv6:** 128-bit; 3.4×10³⁸ addresses; built-in IPsec, SLAAC
- **Private ranges:** 10/8, 172.16/12, 192.168/16

---

## Wi-Fi Generations

|Gen|Standard|Max Speed|Band|
|---|---|---|---|
|Wi-Fi 4|802.11n|600 Mbps|2.4/5 GHz|
|Wi-Fi 5|802.11ac|4 Gbps|5 GHz|
|Wi-Fi 6|802.11ax|10 Gbps|2.4/5/6 GHz|
|Wi-Fi 7|802.11be|46 Gbps|2.4/5/6 GHz|

Key tech: OFDM → MIMO → MU-MIMO → OFDMA (Wi-Fi 6) → MLO (Wi-Fi 7)

### Wi-Fi Security

|Protocol|Status|
|---|---|
|WEP|**NEVER** — broken in minutes|
|WPA|Avoid — deprecated|
|WPA2 (AES-CCMP)|Acceptable minimum|
|**WPA3-Personal (SAE)**|**Recommended**|
|WPA3-Enterprise|Best (gov/high-security)|

> Disable WPS. Legacy IoT: isolate on separate SSID + VLAN.

---

## Ethernet

**Ethernet II frame:** Preamble (7B) + SFD (1B) + Dest MAC (6B) + Src MAC (6B) + EtherType (2B) + Payload (46–1500B) + FCS (4B)  
Min frame 64 bytes (prevents undetected collisions).

|Standard|Speed|Medium|Distance|
|---|---|---|---|
|1000BASE-T|1 Gbps|Cat5e/6|100 m|
|10GBASE-T|10 Gbps|Cat6A|100 m|
|100GBASE-LR4|100 Gbps|SM fiber|10 km|

---

## Cabling Quick Reference

**Coax impedance:** 50 Ω (RF/lab) or 75 Ω (CATV/video)  
Common: RG-58 (50Ω, lab RF), RG-6 (75Ω, CATV), LMR-400 (50Ω, low-loss antenna runs)

**Fiber:**

|Type|Core|Max Distance|
|---|---|---|
|OM3 (MM)|50 μm|300 m @ 10G|
|OM4 (MM)|50 μm|400 m @ 10G|
|OS1 (SM)|9 μm|10 km @ 10G|
|OS2 (SM)|9 μm|80+ km (amplified)|

---

# 3. Port Sniffing (PH585 Lab)

## What Is Port Sniffing?

Capture and analysis of data through a communication interface _without disrupting normal operation._

**Legitimate:** debug lab instruments, reverse-engineer protocols, firmware validation, education.  
**Requires authorization:** penetration testing, SCADA audits.  
**Illegal without permission:** intercepting traffic you don't own — violates CFAA (US), Computer Misuse Act (UK).

> ⚠️ Always get **written authorization** before sniffing any port.

---

## RS-232 Sniffing Essentials

### Voltage Reminder

- Logic 1 = MARK = **negative** (−3 to −15 V)
- Logic 0 = SPACE = **positive** (+3 to +15 V)
- ±3 V = undefined dead zone
- Arduino Nano UART is 0/5V TTL → needs **MAX3232** to convert to RS-232

### Frame Formats

|Format|Description|Use|
|---|---|---|
|8N1|8 data, No parity, 1 stop|90% of instruments|
|8E1|8 data, Even parity, 1 stop|SR510, scientific instruments|
|7E1|7 data, Even parity, 1 stop|Old modems, medical|
|8N2|8 data, No parity, 2 stop|Slow links|

### Baud Rate Quick Reference

|Baud|Bit Period|Bytes/sec|Common Use|
|---|---|---|---|
|9600|104 μs|~960|Lab instruments (SR510, EG&G)|
|19200|52 μs|~1920|GPS, meters|
|115200|8.7 μs|~11520|Modern μC, PortSniffLab|

---

## Passive Tap vs Active MITM

||Passive Y-Tap|Active MITM|
|---|---|---|
|Latency|Zero|Adds latency|
|Detectable?|No|Timing changes detectable|
|Can inject?|No|Yes (risk of rogue commands)|
|Legal|OK if you own the hardware|Needs explicit written authorization|
|Use|Education, debugging, reverse-engineering|Authorized pen-test, fuzzing only|

**→ Always use passive tap in educational labs.**

---

## Tools

|Tool|Use|
|---|---|
|**PySerial**|Python capture: `ser = serial.Serial('COM4', 9600)`|
|**Logic Analyzer + PulseView/sigrok**|Signal-level verification, baud auto-detect|
|**RealTerm / HTerm**|Fast manual inspection|
|**Python script**|Sustained capture, CSV logging, post-processing|

---

## Protocol Decoding Steps

1. **Identify baud rate** — count bit periods (104 μs = 9600 baud), or trial-and-error
2. **Verify frame format** — 8N1 vs 8E1; wrong parity → garbage bytes
3. **Hex → ASCII** — look for `\r` (0x0D) and `\n` (0x0A) as command terminators
4. **Timing analysis** — measure latency between command and response

### Example SR510 Capture

```
DTE→DCE:  53 45 4E 53 3F 0D  →  SENS?\r
DCE→DTE:  31 2E 30 30 45 2D 30 33 0D 0A  →  1.00E-03\r\n
```

---

## Lab Hardware (Nano RS-232 Simulator)

`Arduino Nano (ATmega328P) → MAX3232 (TTL↔RS-232) → DB-9F connector`

- Powered by 9V battery (~45 mA); LED 13 = connection indicator
- Random baud at power-on (9600/19200/38400/57600/115200); short A1→GND to force 115200
- Sends `CUBECTRL:READY:<baud>` every 2 s
- Protocol: `SET_HRYZ:<value>\r` → `DRW_HRYZ:<value>\r\n`
- Cable: FTDI FT232-based USB-A to DB-9 Male

### Lab Tasks Summary

|Task|Goal|
|---|---|
|1|Find correct COM port, baud, frame format|
|2|Capture hex dump, decode ASCII, measure latency|
|3|Passive Y-tap sniff between two stations|
|4|Write Python client using decoded protocol|

---

## Key Takeaways

- RS-232 is **plain ASCII** — no encryption
- Passive tap is undetectable and adds zero latency
- Know frame format _before_ decoding — wrong baud = garbage
- Authorization is non-negotiable, even in a teaching lab