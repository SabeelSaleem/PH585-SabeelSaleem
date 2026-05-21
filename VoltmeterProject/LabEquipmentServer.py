# =============================================================================
# LabEquipmentServer.py  —  runs on your laptop in PyCharm
#
# pip install fastapi uvicorn pyserial
# Run this AFTER disconnecting the MicroPython REPL in PyCharm (see instructions)
# Then open: http://127.0.0.1:8000
# =============================================================================

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
import asyncio
import serial
import serial.tools.list_ports
import json
import threading
import uvicorn

# ── Serial port config ────────────────────────────────────────────────────────
SERIAL_PORT = "COM6"     # ← your ESP32's port
BAUD_RATE   = 115200


# ── Shared state updated by the background reader thread ─────────────────────
_latest = {"voltage": None, "error": None}
_lock   = threading.Lock()


def serial_reader_thread():
    """
    Runs in the background. Continuously reads JSON lines from the ESP32
    and updates _latest so the WebSocket can serve fresh data.
    Automatically reconnects if the port drops.
    """
    import time
    while True:
        try:
            print(f"Opening {SERIAL_PORT} at {BAUD_RATE} baud...")
            with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=2) as ser:
                print("Serial open. Reading from ESP32...")
                while True:
                    line = ser.readline().decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        with _lock:
                            _latest["voltage"] = data.get("voltage")
                            _latest["error"]   = data.get("error")
                    except json.JSONDecodeError:
                        pass  # Ignore garbled lines during startup
        except serial.SerialException as e:
            print(f"Serial error: {e}. Retrying in 3s...")
            with _lock:
                _latest["voltage"] = None
                _latest["error"]   = str(e)
            time.sleep(3)


def get_reading() -> dict:
    with _lock:
        return dict(_latest)


# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI()

html_dashboard = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Voltmeter Dashboard</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@300;600&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background: #0a0c10; color: #e0e6f0;
            font-family: 'Rajdhani', sans-serif;
            min-height: 100vh; display: flex; flex-direction: column;
            align-items: center; justify-content: center; gap: 40px;
        }
        h1 { font-size: 1.1rem; font-weight: 300; letter-spacing: 0.35em;
             text-transform: uppercase; color: #5a6a8a; }
        .card {
            background: #0f1218; border: 1px solid #1e2535; border-radius: 12px;
            padding: 36px 52px; text-align: center; min-width: 380px;
            box-shadow: 0 0 40px rgba(0,180,255,0.04);
        }
        .card-label { font-size: 0.75rem; letter-spacing: 0.25em;
                      text-transform: uppercase; color: #3a4a6a; margin-bottom: 16px; }
        .value {
            font-family: 'Share Tech Mono', monospace; font-size: 3.8rem;
            color: #00e5ff; text-shadow: 0 0 20px rgba(0,229,255,0.35);
            transition: color 0.2s; letter-spacing: 0.04em;
        }
        .value.error { color: #ff4040; text-shadow: 0 0 20px rgba(255,64,64,0.35); }
        .unit { font-size: 1.4rem; color: #3a6080; margin-left: 6px; vertical-align: super; }
        .status-bar { display: flex; align-items: center; gap: 8px; font-size: 0.72rem;
            letter-spacing: 0.15em; color: #2a3a55; margin-top: 18px; justify-content: center; }
        .dot { width: 7px; height: 7px; border-radius: 50%;
               background: #00e5ff; animation: pulse 1.4s ease-in-out infinite; }
        .dot.error { background: #ff4040; animation: none; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.2; } }
        .info { font-size: 0.68rem; color: #2a3a55; letter-spacing: 0.1em; }
    </style>
</head>
<body>
    <h1>BNC Voltmeter &mdash; Live</h1>
    <div class="card">
        <div class="card-label">Input Voltage</div>
        <div>
            <span class="value" id="volt_display">&#8212;</span>
            <span class="unit">V</span>
        </div>
        <div class="status-bar">
            <div class="dot" id="status_dot"></div>
            <span id="status_text">Connecting&hellip;</span>
        </div>
    </div>
    <div class="info">ADS1220 &bull; 24-bit differential &bull; &plusmn;200 V range &bull; 5 Hz</div>
    <script>
        const display   = document.getElementById('volt_display');
        const statusTxt = document.getElementById('status_text');
        const statusDot = document.getElementById('status_dot');
        var ws = new WebSocket("ws://" + location.host + "/ws/voltage");
        ws.onmessage = function(event) {
            var d = JSON.parse(event.data);
            if (d.voltage === null || d.voltage === undefined) {
                display.textContent = "ERR";
                display.classList.add("error");
                statusDot.classList.add("error");
                statusTxt.textContent = d.error || "No data from ESP32";
            } else {
                display.textContent = parseFloat(d.voltage).toFixed(3);
                display.classList.remove("error");
                statusDot.classList.remove("error");
                statusTxt.textContent = "Live — " + new Date().toLocaleTimeString();
            }
        };
        ws.onclose = function() {
            statusTxt.textContent = "Server disconnected";
            statusDot.classList.add("error");
        };
    </script>
</body>
</html>
"""

@app.get("/")
async def get_dashboard():
    return HTMLResponse(html_dashboard)

@app.get("/api/voltage")
def get_voltage():
    return get_reading()

@app.websocket("/ws/voltage")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(get_reading())
            await asyncio.sleep(0.2)
    except Exception:
        print("Client disconnected.")

@app.on_event("startup")
async def startup_event():
    t = threading.Thread(target=serial_reader_thread, daemon=True)
    t.start()

if __name__ == "__main__":
    print("Available serial ports:")
    for p in serial.tools.list_ports.comports():
        print(f"  {p.device}  —  {p.description}")
    print()
    uvicorn.run("LabEquipmentServer:app", host="127.0.0.1", port=8000, reload=False)