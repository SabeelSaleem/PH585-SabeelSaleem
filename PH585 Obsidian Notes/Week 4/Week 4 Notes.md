Oscilloscope probe a wall outlet, you expect to see an oscillating voltage. Peak to peak it is 340V which is odd but it is because of RMS. Using a Multimeter though, you will read 115V.

FOR POWER USAGE: You must use the 340V reading. While both are true, the amplitude of the voltage is 115V as shown by the DMM, the peak to peak is not just 2 * 115V because it is a 3 phase outlet meaning there is an oscillating component as well as an offset. SO by this logic, the non oscillating offset is 110V. 

Wye or Delta when dealing with 3 phase motors. Impedance adds a phase delay. Capacitors bring the voltage signal back into phase. Smith chart.

Impedance takes into account resistance as a function of frequency. 

Resonant Frequency = 1/(2pi * sqrt(LC)) SWR Standing Wave Ratio - Want a really low number (around 1)

Decouple the AC and DC components using a capacitor in series and you can measure just the AC part. 

Buck converter - Light, efficient, but very noisy because it uses a switching power supply which puts the noise through your whole system.
Inductive Kickback is fine for generating high voltage but it is short bursts. MOSFETs cannot handle inductive kickback.  
Transformers are good at transforming low voltage to high voltage but you get power loss. 
Spark Gap (SGTC) - Solid State (SSTC) - Double Resonant (DRSSTC) - Tesla Magnifier (3 Coil)
Piezoelectric HV is good for response time but is extremely short and very low energy. 
Cockcroft-Walton Voltage Multiplier simple and scalable to MV but high output impedance and the ripple gets more noticeable with more stages. 
Marx-Generator can get MV *per stage* and has fast rise time but it is pulsed or single shot only, cannot be continuous wave.

Need a high voltage probe to measure high voltage. An HV Probe is basically a divider with millions of ohms. You also want to make sure the oscilloscope and voltmeter you use is floating with its own battery power, it cannot be on the same ground as the HV circuit. 


