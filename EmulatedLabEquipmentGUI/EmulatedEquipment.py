# EmulatedEquipment.py
import random
import math
import time

def get_dmm_voltage_em():
    """
    Emulated benchtop DMM reading a 5V power supply with +/- 0.02V noise.
    """
    base_voltage = 5.00
    noise = random.uniform(-0.02, 0.02)
    return round(base_voltage + noise, 3)

def get_thermocouple_temp_em():
    """
    Emulated temperature sensor in a slowly heating environment.
    Uses the current time to create a slow, rising curve with slight noise.
    """
    current_time = time.time()
    # Base temp of 20C, rises slowly, oscillates slightly
    base_temp = 20.0 + (math.sin(current_time / 10.0) * 5)
    noise = random.uniform(-0.5, 0.5)
    return round(base_temp + noise, 1)

def get_oscilloscope_wave_em(frequency=1.0, num_points=100):
    """
    Emulated oscilloscope capturing a sine wave.
    Returns an array of data points.
    """
    wave_data = []
    for i in range(num_points):
        # Calculate the time step for the wave
        t = i / num_points
        # Generate a sine wave with the given frequency, plus some noise
        signal = math.sin(2 * math.pi * frequency * t)
        noise = random.uniform(-0.1, 0.1)
        wave_data.append(round(signal + noise, 3))
    return wave_data

# --- Quick Test ---
if __name__ == "__main__":
    print(f"DMM Reading: {get_dmm_voltage_em()} V")
    print(f"Temperature: {get_thermocouple_temp_em()} °C")
    print(f"Scope Trace (first 5 pts): {get_oscilloscope_wave_em()[0:5]}")