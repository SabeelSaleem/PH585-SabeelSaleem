# GUILabEquipment.py
import customtkinter as ctk
import requests

# 1. Setup the visual window
app = ctk.CTk()
app.geometry("350x250")
app.title("Lab Instrument Panel")
ctk.set_appearance_mode("dark")  # Forces a sleek dark theme

# Create the text labels for the window
title_label = ctk.CTkLabel(app, text="Remote DMM", font=("Arial", 20, "bold"))
title_label.pack(pady=(20, 5))

volts_label = ctk.CTkLabel(app, text="-- V", font=("Courier", 40), text_color="#00ff00")
volts_label.pack(pady=10)

temp_label = ctk.CTkLabel(app, text="Temp: -- °C", font=("Arial", 16))
temp_label.pack(pady=5)

# 2. The function that talks to FastAPI
def fetch_lab_data():
    try:
        # Ping the FastAPI server we have running in the background
        response = requests.get("http://127.0.0.1:8000/api/telemetry")
        data = response.json()

        # Update the text on the screen with the new numbers
        volts_label.configure(text=f"{data['voltage']:.3f} V")
        temp_label.configure(text=f"Temp: {data['temperature']:.1f} °C")

    except requests.exceptions.ConnectionError:
        volts_label.configure(text="OFFLINE", text_color="red")

    # Schedule this exact function to run again in 200 milliseconds (5x a second)
    app.after(200, fetch_lab_data)

# 3. Start the loop
fetch_lab_data()  # Kick off the first data pull
app.mainloop()  # Keep the window open and running