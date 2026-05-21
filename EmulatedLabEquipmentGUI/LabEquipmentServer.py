# LabEquipmentServer.py
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
import asyncio
from EmulatedEquipment import get_dmm_voltage_em, get_thermocouple_temp_em
import uvicorn

app = FastAPI()

# This is the HTML and JavaScript for our dashboard.
# FastAPI will send this directly to your web browser.
html_dashboard = """
<!DOCTYPE html>
<html>
    <head>
        <title>Lab Dashboard</title>
        <style>
            body { font-family: Arial; padding: 20px; background-color: #1e1e1e; color: #fff; }
            .reading { font-size: 2em; margin-bottom: 10px; color: #00ff00; font-family: monospace; }
            .label { font-size: 1.2em; color: #aaa; }
        </style>
    </head>
    <body>
        <h1>Real-Time Lab Dashboard</h1>

        <div class="label">Benchtop DMM</div>
        <div class="reading" id="dmm_display">Waiting for data...</div>

        <div class="label">Thermocouple Chamber</div>
        <div class="reading" id="temp_display">Waiting for data...</div>

        <script>
            // This JavaScript opens the WebSocket tunnel back to our FastAPI server
            var ws = new WebSocket("ws://127.0.0.1:8000/ws/telemetry");

            // Every time the server pushes data down the tunnel, this function updates the screen
            ws.onmessage = function(event) {
                var lab_data = JSON.parse(event.data);
                document.getElementById('dmm_display').innerText = lab_data.voltage + " V";
                document.getElementById('temp_display').innerText = lab_data.temperature + " °C";
            };
        </script>
    </body>
</html>
"""

# Window 1: Serving the webpage
@app.get("/")
async def get_dashboard():
    return HTMLResponse(html_dashboard)

@app.get("/api/telemetry")
def get_telemetry():
    # This is a standard endpoint that returns the current data as JSON
    return {
        "voltage": get_dmm_voltage_em(),
        "temperature": get_thermocouple_temp_em()
    }

# Window 2: The WebSocket Tunnel
@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    # Accept the connection from the browser
    await websocket.accept()

    try:
        # Loop forever, continuously pushing data
        while True:
            # 1. Grab the virtual data from our emulator
            current_volts = get_dmm_voltage_em()
            current_temp = get_thermocouple_temp_em()

            # 2. Package it into a dictionary and send it as JSON over the tunnel
            await websocket.send_json({
                "voltage": current_volts,
                "temperature": current_temp
            })

            # 3. Wait 0.2 seconds before grabbing the next reading (5 updates per second)
            await asyncio.sleep(0.2)

    except Exception as e:
        # If the user closes the browser tab, the connection drops cleanly
        print("Dashboard disconnected.")

if __name__ == "__main__":
    uvicorn.run("LabEquipmentServer:app", host="127.0.0.1", port=8000, reload=True)