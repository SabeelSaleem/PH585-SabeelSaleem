# Laser Physics Notes

---

## What is a LASER?

**L**ight **A**mplification by **S**timulated **E**mission of **R**adiation

|Property|Description|
|---|---|
|**Coherent**|All photons in phase → enables interference, holography, fiber optics|
|**Collimated**|Very low divergence — travels long distances without spreading|
|**Monochromatic**|Extremely narrow spectral linewidth|

> Ordinary light = spontaneous, incoherent, broad spectrum. Laser = stimulated, coherent, narrow.

---

## Einstein Coefficients & Stimulated Emission

Three interaction processes between light and atoms:

|Process|Symbol|Rate|Notes|
|---|---|---|---|
|Absorption|B₁₂|B₁₂·ρ(ν)·N₁|Atom absorbs photon, jumps to higher level|
|Spontaneous Emission|A₂₁|A₂₁·N₂|Random direction & phase. Basis of LEDs/fluorescence|
|Stimulated Emission|B₂₁|B₂₁·ρ(ν)·N₂|Incoming photon triggers **identical copy** — same energy, direction, phase. **The laser process.**|

**Einstein Relations:** $$A_{21} = \frac{8\pi h\nu^3}{c^3} B_{21}, \quad B_{12} = B_{21} \text{ (non-degenerate levels)}$$

---

## Population Inversion & Threshold

**Why inversion is needed:**

- Thermal equilibrium (Boltzmann): N₂ < N₁ → absorption dominates → no lasing
- Inversion (N₂ > N₁): stimulated emission dominates → optical gain G = σ·(N₂−N₁)·L > 1

**Four-level scheme** is preferred: fast non-radiative decay keeps lower laser level depopulated, making inversion easier to achieve.

**Key equations:** $$\frac{dN_2}{dt} = W_p N_1 - A_{21}N_2 - B_{21}\rho N_2$$ $$\text{Threshold condition: } G \cdot R_1 R_2 = 1$$

---

## Optical Resonator Basics

```
[HR Mirror >99.9%] --- [Gain Medium] --- [OC Mirror ~90-99%] → Output beam
|<--------------------- Cavity Length L ---------------------->|
```

|Component|Role|
|---|---|
|**Gain Medium**|Crystal/gas providing optical amplification|
|**HR Mirror**|High-reflector (R > 99.9%) — rear of cavity|
|**OC Mirror**|Output coupler (R ~ 90–99%) — transmits output beam|
|**Pump Source**|Diode laser, flashlamp, or discharge|
|**Intracavity elements**|Q-switch, etalon, SHG crystal, aperture|

### Cavity Stability: g-Parameters

$$g_i = 1 - \frac{L}{R_i}, \quad \text{Stability condition: } 0 \leq g_1 \cdot g_2 \leq 1$$

|Configuration|g values|Stability|
|---|---|---|
|Plane-Plane|g₁=g₂=1|Marginally stable|
|Concentric|g₁=g₂=−1|Marginally stable|
|Confocal|g₁=g₂=0|Always stable|
|Hemispherical|one flat, one concave|Very common, practical|
|Near-concentric|g₁g₂ → 1⁻|High finesse but alignment-sensitive|

---

## Gaussian Beams & Transverse Modes

### Gaussian Beam Propagation (TEM₀₀)

|Parameter|Formula|Meaning|
|---|---|---|
|Beam radius|w(z) = w₀·√(1 + (z/z_R)²)|Expands from waist w₀|
|Rayleigh range|z_R = πw₀²/λ|Distance over which beam doubles in area|
|Far-field divergence|θ = λ/(πw₀)|Smaller waist → larger divergence (diffraction)|
|Beam quality|M² = actual/ideal divergence|M²=1 is perfect Gaussian; higher = worse|

### Transverse Modes (TEMₘₙ)

- **TEM₀₀**: Lowest order, single lobe, best beam quality → used in most applications
- **Higher-order modes** (TEM₁₀, TEM₁₁, etc.): Multiple lobes, more power but larger M²
- **Mode selection**: An intracavity aperture forces TEM₀₀ (lowest loss mode) at slight cost to power

---

## Gain, Threshold & Slope Efficiency

$$g_{th} = \frac{-\ln(R_1 R_2) + 2\alpha_i L}{2L}$$

$$P_{th} = \frac{h\nu_p \cdot \pi w_0^2 \cdot L \cdot g_{th}}{\sigma_e \cdot \tau_f \cdot \eta_{abs}}$$

$$\eta_{slope} = \frac{\lambda_p}{\lambda_l} \cdot \eta_{abs} \cdot \eta_{mode} \cdot \frac{T}{T + L_{int}}$$

$$P_{out} = \eta_{slope} \cdot (P_{pump} - P_{th})$$

- Below threshold: no output. Above: linear ramp with slope η
- **Optimal OC** (Rigrod): $R_{opt} \approx 1 - \sqrt{L_{int} \cdot 2g_0 L_c}$

---

## Laser Types — Key Properties

### Solid-State & Gas Lasers

|Laser|Wavelength|Power/Energy|Pulse|Application|
|---|---|---|---|---|
|Nd:YAG|1064 nm (+harmonics)|CW: 200 W / Pulsed: 1 J|ns–CW|Industry, surgery, rangefinding|
|Nd:YVO₄|1064 nm (+532 SHG)|CW: 20 W|ps–CW|Laser printers, microfab|
|Yb:YAG|1030 nm|kW (fiber)|fs–CW|Material processing|
|Ti:Sapphire|700–1100 nm (tunable)|CW: 10 W|fs–CW|Ultrafast science, spectroscopy|
|Ruby|694.3 nm|J-level|ms–μs|Historical, holography|
|He-Ne|632.8 nm|1–50 mW|CW|Alignment, interferometry|
|Ar-Ion|488, 514 nm|1–20 W|CW|Ophthalmology, microscopy|
|CO₂|10.6 μm|1 W–100 kW|μs–CW|Cutting, welding, surgery|

### Fiber & Diode Lasers

|Laser|Wavelength|Power|Key Advantage|Limitation|
|---|---|---|---|---|
|Yb Fiber|1070 nm|100 W–100 kW|~80% efficiency, excellent beam quality|Nonlinear effects at high power|
|Er Fiber|1550 nm|10–100 W|Eye-safe, telecom compatible|Lower power than Yb|
|Tm Fiber|2000 nm|50 W+|Eye-safe, good tissue absorption|Younger technology|
|Diode|630–1900 nm|mW–kW|Tiny, ~60% efficient, direct modulation|Poor beam quality (M²>>1)|
|Excimer|157–351 nm (UV)|up to 1 kW avg|Very short λ, fine ablation|Short lifetime, halogen gas|
|QCL|3–20 μm (MIR)|mW–W|Compact MIR, room temperature|Limited to MIR|

---

## Pulsed Techniques

### Q-Switching (ns pulses, kW–MW peak power)

**Mechanism:**

1. **Block cavity** — high loss (low Q): inversion builds far above threshold, gain stored
2. **Open cavity** — suddenly restore high Q (via rotating mirror, EO cell, or AO modulator)
3. **Giant pulse** — stored energy dumps as a nanosecond pulse
4. **Repeat** — typically 1–100 kHz rep rate

$$P_{peak} = \frac{E_{pulse}}{\tau_{pulse}}, \quad \text{e.g. } 1\text{ mJ} / 10\text{ ns} = 100\text{ kW}$$

### Mode Locking (ps–fs pulses)

**Mechanism:** Lock N longitudinal modes in phase → coherent superposition → ultrashort pulse

|Parameter|Formula / Value|
|---|---|
|Pulse duration|Δt ≈ 1/Δν_gain (Fourier limit) — broader gain bandwidth = shorter pulse|
|Repetition rate|f_rep = c/2L — typically 50–500 MHz|
|Peak power|P_peak = E_pulse · f_rep / duty cycle >> CW power|

**Methods:**

- **Active ML**: AOM modulates loss at f_rep — forces mode locking
- **Passive ML**: SESAM or Kerr lens — intensity-dependent loss auto-locks modes

**Typical pulse widths:** Ti:Sapphire: 5–50 fs | Yb fiber: 100–500 fs | Nd:YAG: 10–100 ps

---

## Nonlinear Optics: Second Harmonic Generation (SHG)

**Phase matching condition:** $\Delta k = k_{2\omega} - 2k_\omega = 0$

**SHG efficiency (plane wave):** $\eta \propto d_{eff}^2 \cdot L^2 \cdot P / w^2$

> Intracavity SHG: circulating power >> output power → much higher conversion efficiency

### Common SHG Crystals

|Crystal|d_eff|Conversion|Type|
|---|---|---|---|
|KTP|3.18 pm/V|1064→532 nm|Type II|
|BBO|2.01 pm/V|800→400 nm|Type I|
|LBO|0.83 pm/V|1064→532 nm|Type I NCPM|
|PPLN|14 pm/V|1064→532 nm|Quasi Phase Matching|
|BiBO|3.7 pm/V|any→vis|Type I|

> PPLN has by far the highest effective nonlinearity due to quasi-phase matching.

---

## Key Equations Summary

|Quantity|Formula|
|---|---|
|Stimulated emission rate|B₂₁·ρ(ν)·N₂|
|Optical gain|G = σ(N₂−N₁)L|
|Threshold gain|g_th = [−ln(R₁R₂) + 2αᵢL] / 2L|
|Output power|P_out = η_slope · (P_pump − P_th)|
|Gaussian beam radius|w(z) = w₀√(1+(z/z_R)²)|
|Rayleigh range|z_R = πw₀²/λ|
|g-parameter|gᵢ = 1 − L/Rᵢ|
|Cavity stability|0 ≤ g₁g₂ ≤ 1|
|Q-switch peak power|P_peak = E_pulse/τ_pulse|
|Mode-lock rep rate|f_rep = c/2L|
|SHG phase match|Δk = k₂ω − 2kω = 0|

---

## References

- Saleh & Teich — _Fundamentals of Photonics_
- Siegman — _Lasers_
- Yariv & Yeh — _Photonics_