# PH585 — UV Multi-Wavelength Laser Lab Notes

---

## Lab Overview

Three independent Python drivers to write **from scratch** (no vendor libraries):

|Subsystem|Interface|What you get|
|---|---|---|
|**Laser Controller**|RS-232 (DB-9, null-modem)|Power, temperature, fault status, enable control|
|**CCD Spectrometer**|USB or Bluetooth SPP|2048-pixel spectrum → λ₀ (UV main) + λ₁/λ₂ (residuals)|
|**Photodiode Power Meter**|You build it (TIA + ADC)|Optical power calibrated against NIST reference|

**Target laser:** Class 4 UV DPSS, mode-locked (high-rep-rate pulse train, ~100 MHz), wavelengths λ₀ (UV main), λ₁, λ₂ (residual harmonics).

---

## ⚠️ Safety — Class 4 UV

> **No blink reflex at UV wavelengths** — cornea is opaque to λ₀, so damage to lens/retina occurs **without warning**.

### Pre-flight checklist (every session)

- [ ] UV-rated PPE: OD ≥ 5 goggles (check OD label on lens), lab coat, closed shoes
- [ ] Beam fully enclosed or terminated on absorbing beam dump — **no shiny surfaces, watches, tools**
- [ ] Door sign on, room access controlled
- [ ] Key switch in **DISABLE**
- [ ] Manual shutter **CLOSED** (orange dot visible)
- [ ] External interlock plug installed
- [ ] Meters connected before enabling

### Emission gates — ALL must be true simultaneously

1. Key switch → **ENABLE**
2. External interlock loop **closed**
3. No active fault
4. Software command `Laser Enable ON` issued (deliberate toggle required — see Class 4 sequence below)
5. Manual shutter **OPEN** (only this one cannot be done in software)

### ⚡ Warm-up warning

Output power is **unregulated for 15–30 minutes** after cold start — can exceed rated average power. Wait for READY indicator solid before trusting setpoints.

---

## Section 4 — Laser Controller Protocol (RS-232)

### Physical Layer

|Parameter|Value|
|---|---|
|Connector|DB-9 female (controller side)|
|Cable|**Null-modem** ≤ 3 m (straight-through will NOT work)|
|Baud|**38400**, fixed|
|Frame|8N1|
|Flow control|**RTS/CTS hardware** (controller asserts RTS; you assert CTS)|

**DB-9 pinout (controller female):**

|Pin|Signal|Direction|Function|
|---|---|---|---|
|2|RxD|→ controller|Your TxD|
|3|TxD|← controller|Your RxD|
|5|GND|—|Signal ground|
|7|RTS|← controller|Always asserted|
|8|CTS|→ controller|You assert when ready|

### Command Frame Format

```
ESC | '0' | <cmd> | <par> | [w][x][y][z] | LF | CR
0x1B  0x30   3?      ??      (4 ASCII chars,   0x0A 0x0D
                              write only)
```

> **⚠️ Terminator is LF then CR** — opposite the usual CR-LF convention.

**Ping / sync:** Send a bare `0x1B` (ESC, nothing else) → controller replies `?` (no terminator). Do this first to verify link.

### Action Codes (3rd byte)

|ASCII|Hex|Meaning|Data payload?|
|---|---|---|---|
|`'0'`|0x30|Increment parameter|No|
|`'1'`|0x31|Decrement parameter|No|
|`'2'`|0x32|Turn ON|No|
|`'3'`|0x33|Turn OFF|No|
|`'4'`|0x34|Read current value|No|
|`'5'`|0x35|Read default value|No|
|`'6'`|0x36|Make current = default|No|
|`'7'`|0x37|Set to default|No|
|`'8'`|0x38|Start procedure|No|
|`'9'`|0x39|**Set to given value**|**Yes — 4 ASCII chars**|

### Key Parameter Codes (4th byte)

|Param|Hex|Quantity|R|W|On/Off|
|---|---|---|---|---|---|
|`'0'`|0x30|Model ID|✓|||
|`'1'`|0x31|Head serial number|✓|||
|`'6'`|0x36|Laser ENABLE|✓|✓|✓|
|`'7'`|0x37|Optical power monitor (mW)|✓|||
|`'8'`|0x38|Interlock status|✓|||
|`'9'`|0x39|Fault status|✓|||
|`'C'`|0x43|Pump diode temp (°C)|✓|||
|`'E'`|0x45|Head heat-sink temp (°C)|✓|||
|`'J'`|0x4A|Pump diode current setpoint (A)|✓|||
|`'P'`|0x50|Power setpoint (mW) / CL control|✓|✓|✓|
|`'R'`|0x52|Closed-loop READY state|✓|||
|`'T'`|0x54|Mode-locker element temp|✓|||
|`'W'`|0x57|SHG crystal temp|✓|||
|`'Z'`|0x5A|THG crystal temp|✓|||

### Reply Format

ASCII text terminated with **LF CR**. Parse examples:

```
Read power:     → "Sensed Power 19.9 mW"
Read enable:    → "ON" or "OFF"
Read ready:     → "Ready" or "Not Ready"
Read interlock: → "ILOCK CLSD" or "ILOCK OPEN"
Read fault:     → "No SP faults" or e.g. "SBR over Temperature"
```

### Writing a Setpoint (action `'9'`)

4-byte ASCII, right-padded with decimal:

|Target|Send|
|---|---|
|0.5 mW|`"0.50"`|
|20 mW|`"20.0"`|
|100 mW|`"100."`|
|150 mW|`"150."`|

> Common bug: left-zero-padding (`"020."`) works but is confusing. Use right-padded forms.

### Driver Bring-up Order

1. Open port: 38400, 8N1, RTS/CTS on
2. Send bare ESC → expect `?` within 200 ms
3. Read identity: Model ID, Head SN, FW rev, service hours
4. Read interlock / ready / enable / fault → display as status indicators
5. Read all temperatures + pump current (health signals during warm-up)
6. Start background poll thread: re-read dynamic quantities (power, ready, fault, temps) every **0.5–2 s** — don't poll faster
7. Only then attempt the enable sequence

### Class 4 Enable Sequence

```
Send: action=3, par=6  (Turn OFF Enable)
Wait: 0.5 s
Send: action=2, par=6  (Turn ON Enable)
```

> Class 3B (≤ 100 mW) auto-enables on key turn. Class 4 requires this deliberate toggle.

After enable: READY transitions "Not Ready" → "Ready" once feedback loop converges. Can take **10+ minutes** from cold.

---

## Section 5 — Spectrometer Protocol

**Hardware:** 2048-pixel CCD array, ~190–880 nm range. Light enters via fiber → entrance slit → collimator → grating → focus mirror → CCD.

> **Never shine directly into the fiber** — always diffuse the beam first.

### Physical Layer

|Parameter|Value|
|---|---|
|Connection|Mini-USB (FTDI inside) or Bluetooth SPP|
|Default baud|**9600** (always at power-on)|
|Fast baud|**115200** (after K0 command)|
|Frame|8N1, no flow control|
|Line endings|Commands: CR LF. Replies: vary.|
|Power|**5 V only** — over-voltage will damage the module|

### Command Set

|Command|Arg|Effect|
|---|---|---|
|`K`|0–7|Change baud (K0 = 115200, K3 = 9600 default)|
|`I`|ms|Set integration time|
|`A`|1–N|Set hardware averaging count|
|`S`|—|Acquire one spectrum → ACK + binary frame|
|`?I`|—|Query current integration time|

> After a `K` command, ACK comes back at the **old** baud, then the module switches. Wait ~200 ms before sending at new rate.

### Spectrum Acquisition Flow

```
TX: S CR LF
RX: ACK CR LF
RX: <compressed binary frame>  (~2400–4200 bytes)
→ decompress → 2048 × uint16 pixel values
```

### Decompression Scheme (mixed delta + absolute)

- **0x80 marker** → next 2 bytes = big-endian uint16 absolute value (resets running value)
- **Any other byte** → signed int8 delta; add to running value; clamp 0–65535
- Continue until 2048 pixels produced

```python
def decompress(bytes_in) -> list[int]:
    pixels = []; prev = 0; i = 0
    while i < len(bytes_in) and len(pixels) < 2048:
        b = bytes_in[i]
        if b == 0x80:
            val = (bytes_in[i+1] << 8) | bytes_in[i+2]
            pixels.append(val); prev = val; i += 3
        else:
            delta = b if b < 128 else b - 256
            val = max(0, min(65535, prev + delta))
            pixels.append(val); prev = val; i += 1
    return pixels
```

### Wavelength Calibration

Fit a quadratic polynomial through known emission lines:

$$\lambda(p) = ap^2 + bp + c$$

**Reference lines:**

|Source|Wavelength (nm)|
|---|---|
|Hg pen-lamp|253.65, 404.66, 435.83, 546.07, 578.97|
|Ne lamp|585.25, 640.22|
|UV laser λ₀|Use to verify fit|

**Procedure:**

1. Illuminate slit with Hg/Ne lamp
2. Find peak centroids (sub-pixel: Gaussian or parabolic fit over 3–5 pixels around each peak)
3. Least-squares fit: 1 point = offset only; 2 points = slope + offset; **3+ points = quadratic**
4. Save coefficients to `calibration.json` — no need to recalibrate every session

---

## Section 6 — Photodiode Power Meter (TIA Design)

### Circuit Topology

Photodiode in **photovoltaic (zero-bias) mode** → TIA (op-amp with Rf, Cf feedback) → ADC → microcontroller.

Zero-bias eliminates dark-current dependence on voltage → clean linear response over many decades.

### Key Equations

$$V_{out} = -I_{ph} \cdot R_f$$

$$P_{optical} = \frac{I_{ph}}{R(\lambda)}$$

$$f_{3dB} \approx \frac{1}{2\pi R_f C_f}$$

> For a UV-enhanced Si PD: R(λ₀) ≈ **0.10–0.15 A/W** — must be measured against reference, datasheet is typical only.

> The source pulses at ~100 MHz (mode-locked). You **don't want** bandwidth to follow pulses — set f₃dB << 1 kHz so the TIA averages power naturally.

### Design Targets

|Parameter|Target|Notes|
|---|---|---|
|Rf|1 kΩ – 100 kΩ|Choose for Vout ≈ 2–3 V full-scale. Use ≤ 0.1% precision resistor.|
|Cf|10–100 pF|Calculate from f₃dB; round **up** to avoid oscillation|
|Op-amp|FET-input, low Ib, rail-to-rail, ≥ 1 MHz GBW|Ib must be << min Iph (~pA-range)|
|ADC|**≥ 16-bit**|Need ~4 decades dynamic range; 12-bit not sufficient|
|Accuracy goal|≤ 5% vs reference|After calibration, across two decades of power|

### Calibration Procedure

Setup: 50:50 beam splitter → one arm to NIST reference meter, other arm to your DUT. Both logged simultaneously.

1. Warm laser fully (READY solid); set ~50 mW
2. Insert splitter, verify clean beam on both detectors (no clipping)
3. Block each arm in turn to verify responses
4. Measure splitter ratio k = P_DUT / P_ref (note: polarization-sensitive — stabilize k)
5. Sweep setpoints: 5, 10, 20, 50, 100, 150 mW — log reference, Vout, and laser internal monitor at each point
6. Plot Vout vs (k × P_ref); fit line through zero → slope = Rf × R(λ)
7. Check residuals < 5% everywhere (if not: check PD saturation, TIA clipping, splitter angle)
8. Save slope + offset to disk for firmware runtime use

---

## Section 7 — Lab Procedure & Deliverables

### Procedure Steps

1. Demo laser driver: live read of identity, temperatures, fault/interlock/ready, successful Class-4 enable (no emission yet)
2. Demo spectrometer driver: acquire raw Hg pen-lamp spectrum
3. Calibrate spectrometer (2–3 point Hg fit), save JSON
4. Enable UV laser → acquire spectrum → identify λ₀ peak + FWHM + residual λ₁/λ₂ lines
5. Build power meter, calibrate against reference (Section 6.4)
6. Record power vs setpoint (5–150 mW in 5 mW steps) using only your meter + laser internal monitor
7. Plot your meter, laser monitor, and reference together; discuss offsets
8. 10-minute stability log at 50 mW (≥ 1 Hz) → compute RMS noise and peak-to-peak drift

### Deliverables

|Item|Description|
|---|---|
|Source code|Python drivers + firmware, with README|
|Calibration JSON|Spectrometer polynomial coefficients|
|Power meter plot|Calibration curve + JSON of coefficients|
|Spectrum plot|λ₀ peak annotated with FWHM + labeled λ₁/λ₂ lines|
|Stability log plot|10 min, ≥ 1 Hz, RMS + peak-to-peak reported|
|Written discussion|≤ 2 pages: agreement with laser monitor, disagreements, uncertainty sources|

### Grading Rubric

|Component|Points|
|---|---|
|Laser driver (read + enable + setpoint)|20|
|Spectrometer driver + calibrated wavelength axis|20|
|Power meter hardware + firmware|20|
|Calibration plot, < 5% agreement|15|
|Spectrum analysis|10|
|Written discussion + figures|15|

---

## Quick Reference — Common RS-232 Commands

```
1B                              → Ping (expect "?")
1B 30 34 30 0A 0D               → Read Model ID
1B 30 34 36 0A 0D               → Read Laser Enable
1B 30 32 36 0A 0D               → Set Enable ON
1B 30 33 36 0A 0D               → Set Enable OFF
1B 30 34 37 0A 0D               → Read Sensed Power (mW)
1B 30 34 52 0A 0D               → Read Ready state
1B 30 34 38 0A 0D               → Read Interlock
1B 30 34 39 0A 0D               → Read Fault status
1B 30 39 50 32 31 2E 33 0A 0D   → Set power = "21.3" mW
1B 30 34 43 0A 0D               → Read pump diode temp
1B 30 34 57 0A 0D               → Read SHG crystal temp
1B 30 34 5A 0A 0D               → Read THG crystal temp
```

## Quick Reference — Spectrometer Commands

```
K0 CR LF      → Switch to 115200 baud
K3 CR LF      → Switch to 9600 baud (safe fallback)
I 100 CR LF   → Integration time = 100 ms
A 1 CR LF     → No averaging
A 5 CR LF     → Average 5 frames
?I CR LF      → Query integration time
S CR LF       → Acquire spectrum
```

---

## Key Gotchas & Tips

- RS-232 terminator is **LF then CR** (0x0A 0x0D) — not the usual CR-LF
- **Null-modem cable required** — straight-through will not work
- Don't poll the laser controller faster than every 0.5 s
- Send bare ESC first to sync/clear controller buffer before any real commands
- Spectrometer K command: ACK returns at **old** baud; wait 200 ms then switch
- TIA bandwidth: **intentionally low** (< 1 kHz) so it time-averages the mode-locked pulse train
- ADC must be ≥ 16-bit for 4 decades of dynamic range
- Measure R(λ₀) yourself — don't trust the datasheet value for calibration
- Spectrometer: never direct-couple laser to fiber — diffuse first

_Last revised: 2026-05-13_