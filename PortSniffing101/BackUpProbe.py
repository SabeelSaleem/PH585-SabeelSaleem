"""
PH585 -- PortSniffLab Protocol Decoder + Client
================================================
Arduino Nano + MAX3232 RS-232 simulator.
Auto-detects baud rate and decodes the full SET_/DRW_ protocol.

USAGE MODES:
  python MysteryBlackBoxProbe.py detect              -- Auto-detect baud rate (run FIRST)
  python MysteryBlackBoxProbe.py direct [baud]       -- Read-only tap from box (close PortSniffLab)
  python MysteryBlackBoxProbe.py sniff  [baud]       -- Proxy MITM (needs com0com, PortSniffLab open)
  python MysteryBlackBoxProbe.py client [baud]       -- Interactive client: send SET_ commands yourself
  python MysteryBlackBoxProbe.py demo   [baud]       -- Auto-demo: sweep all parameters and log results
  python MysteryBlackBoxProbe.py decode <file>       -- Decode an existing .log file

INSTALL:
  pip install pyserial
"""

import serial
import serial.tools.list_ports
import threading
import time
import sys
import os
from datetime import datetime

# --- CONFIGURATION -----------------------------------------------------------

BOX_PORT      = "COM7"
BAUD_RATES    = [9600, 19200, 38400, 57600, 115200]
FRAME_FORMAT  = dict(bytesize=serial.EIGHTBITS,
                     parity=serial.PARITY_NONE,
                     stopbits=serial.STOPBITS_ONE)

VIRT_SW_PORT  = "COM9"   # Python side of com0com pair (PortSniffLab uses COM8)

LOG_FILE      = "cubectrl_capture.log"

# --- KNOWN PROTOCOL ----------------------------------------------------------
#
#   DEVICE SENDS ON BOOT (every 2s):
#       CUBECTRL:READY:<baudrate>
#
#   HANDSHAKE:
#       PC  ->  CUBECTRL:CONNECT
#       BOX ->  ACK_CONN:OK
#
#   COMMANDS (PC -> BOX -> echo back):
#       SET_HRYZ:<0-359>   ->  DRW_HRYZ:<val>    H-Rotation slider
#       SET_VRYZ:<0-359>   ->  DRW_VRYZ:<val>    V-Rotation slider
#       SET_HUE:<0-359>    ->  DRW_HUE:<val>     Color Hue slider
#       SET_BRT:<20-200>   ->  DRW_BRT:<val>     Brightness slider
#       SET_ZOM:<val>      ->  DRW_ZOM:<val>     Zoom slider
#       SET_SHP:<name>     ->  DRW_SHP:<name>    Shape selector
#
#   All lines terminated with \r\n (0x0D 0x0A)
#
#   Known shape names:
#       Square_D6, Sphere_D1, Tetra_D4, Octa_D8, Dodeca_D12, Icosa_D20
# -----------------------------------------------------------------------------

COMMAND_MAP = {
    "SET_HRYZ": "H-Rotation",
    "SET_VRYZ": "V-Rotation",
    "SET_HUE":  "Color Hue",
    "SET_BRT":  "Brightness",
    "SET_ZOM":  "Zoom",
    "SET_SHP":  "Shape",
    "CUBECTRL": "Handshake/Ready",
    "ACK_CONN": "Handshake ACK",
    "DRW_HRYZ": "  Echo H-Rotation",
    "DRW_VRYZ": "  Echo V-Rotation",
    "DRW_HUE":  "  Echo Color Hue",
    "DRW_BRT":  "  Echo Brightness",
    "DRW_ZOM":  "  Echo Zoom",
    "DRW_SHP":  "  Echo Shape",
}

KNOWN_SHAPES = [
    "Square_D6",
    "Sphere_D1",
    "Tetra_D4",
    "Octa_D8",
    "Dodeca_D12",
    "Icosa_D20",
]


def clean_line(raw):
    """
    Strip garbage bytes that SoftwareSerial sometimes emits at the start of a
    transmission. Keeps only printable ASCII (32-126), then scans forward to
    the first alphabetic character so stray punctuation from framing errors
    does not corrupt the prefix match.
    """
    cleaned = ""
    for ch in raw:
        if 32 <= ord(ch) <= 126:
            cleaned += ch
    i = 0
    while i < len(cleaned) and not cleaned[i].isalpha():
        i += 1
    return cleaned[i:]


def decode_line(raw):
    """Turn a raw protocol line into a human-readable description."""
    raw = clean_line(raw.strip())
    for prefix, label in COMMAND_MAP.items():
        if raw.startswith(prefix):
            return "%-25s | %s" % (label, raw)
    return "%-25s | %s" % ("UNKNOWN", raw)


def send_command(ser, cmd, log_fh=None):
    """
    Send a command string to the box (adds \\r\\n terminator).
    Waits up to 500ms for a DRW_ or ACK_ response line and returns it.
    Logs to log_fh if provided.
    Returns the cleaned response string, or "" on timeout.
    """
    full_cmd = cmd.strip() + "\r\n"
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    entry_out = "[%s] PC->BOX  %-25s | %s" % (ts, "PC Command", cmd.strip())
    print(entry_out)
    if log_fh:
        log_fh.write(entry_out + "\n")
        log_fh.flush()

    ser.write(full_cmd.encode("ascii"))

    deadline = time.time() + 0.5
    rx_buf = ""
    while time.time() < deadline:
        data = ser.read(ser.in_waiting or 1)
        if data:
            rx_buf += data.decode("ascii", errors="replace")
            while "\n" in rx_buf:
                line, rx_buf = rx_buf.split("\n", 1)
                line_clean = clean_line(line.strip())
                if not line_clean:
                    continue
                ts2 = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                decoded = decode_line(line_clean)
                entry_in = "[%s] BOX->PC  %s" % (ts2, decoded)
                print(entry_in)
                if log_fh:
                    log_fh.write(entry_in + "\n")
                    log_fh.flush()
                if line_clean.startswith("DRW_") or line_clean.startswith("ACK_"):
                    return line_clean
    return ""


def do_handshake(ser, log_fh=None):
    """
    Send CUBECTRL:CONNECT and wait for ACK_CONN:OK.
    Returns True on success.

    SoftwareSerial on the Nano sometimes prepends a garbage byte to the first
    transmitted frame, so we do a substring search on the raw receive buffer
    rather than requiring a perfectly clean line match.
    """
    print("\n[HANDSHAKE] Sending CUBECTRL:CONNECT ...")
    time.sleep(0.1)
    ser.reset_input_buffer()

    full_cmd = "CUBECTRL:CONNECT\r\n"
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    entry_out = "[%s] PC->BOX  %-25s | CUBECTRL:CONNECT" % (ts, "PC Command")
    print(entry_out)
    if log_fh:
        log_fh.write(entry_out + "\n")
        log_fh.flush()

    ser.write(full_cmd.encode("ascii"))

    # Read for up to 500ms, processing one complete line at a time.
    # The box echoes our command first, then sends ACK_CONN:OK, then READY.
    # We check each line_clean directly after splitting it out of the buffer.
    deadline = time.time() + 0.5
    rx_buf = ""
    while time.time() < deadline:
        data = ser.read(ser.in_waiting or 1)
        if data:
            rx_buf += data.decode("ascii", errors="replace")
            while "\n" in rx_buf:
                line, rx_buf = rx_buf.split("\n", 1)
                line_clean = clean_line(line.strip())
                if not line_clean:
                    continue
                ts2 = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                decoded = decode_line(line_clean)
                entry_in = "[%s] BOX->PC  %s" % (ts2, decoded)
                print(entry_in)
                if log_fh:
                    log_fh.write(entry_in + "\n")
                    log_fh.flush()
                # Check the line we just pulled out, not rx_buf (ACK is already
                # consumed from rx_buf by the time we get here)
                if "ACK_CONN:OK" in line_clean:
                    print("[HANDSHAKE] Connected!\n")
                    return True

    print("[HANDSHAKE] No ACK received. Last raw buffer: %r" % rx_buf[:80])
    print("            Check baud rate and that PortSniffLab is closed.\n")
    return False


# --- MODE 1: AUTO-DETECT BAUD ------------------------------------------------

def detect_baud():
    """
    Try each baud rate and listen for CUBECTRL:READY.
    Device broadcasts every ~2 seconds; we wait up to 5s per rate.
    Returns the detected baud rate, or None.
    """
    print("=" * 60)
    print("  BAUD RATE AUTO-DETECTION")
    print("  Close PortSniffLab before running this!")
    print("=" * 60)

    for baud in BAUD_RATES:
        print("\n[...] Trying %d baud " % baud, end="", flush=True)
        try:
            with serial.Serial(BOX_PORT, baud, timeout=0.5, **FRAME_FORMAT) as ser:
                deadline = time.time() + 5.0
                buffer = ""
                while time.time() < deadline:
                    chunk = ser.read(64).decode("ascii", errors="replace")
                    buffer += chunk
                    print(".", end="", flush=True)
                    if "CUBECTRL:READY" in buffer:
                        for line in buffer.splitlines():
                            if "CUBECTRL:READY" in line:
                                embedded_baud = line.split(":")[-1].strip()
                                print("\n\n    FOUND IT at %d baud!" % baud)
                                print("    Raw message   : %s" % line.strip())
                                print("    Embedded baud : %s" % embedded_baud)
                                print("\n    Use 'direct %d' or 'client %d' next." % (baud, baud))
                                return baud
        except serial.SerialException as e:
            print("\n  [ERROR] %s" % e)
            return None

    print("\n\n  No CUBECTRL:READY received at any baud rate.")
    print("  Check: Is PortSniffLab closed? Is the box powered on?")
    return None


# --- MODE 2: DIRECT READ (passive tap) ---------------------------------------

def direct_sniff(baud):
    """
    Open COM7 directly and log + decode everything passively.
    PortSniffLab must be closed.
    """
    print("\n[DIRECT] Opening %s at %d baud (8N1) -- read-only tap" % (BOX_PORT, baud))
    print("[DIRECT] Press Ctrl+C to stop. All traffic saved to: %s" % LOG_FILE)
    print("-" * 70)

    try:
        ser = serial.Serial(BOX_PORT, baud, timeout=0.1, **FRAME_FORMAT)
    except serial.SerialException as e:
        print("[ERROR] Cannot open %s: %s" % (BOX_PORT, e))
        return

    with open(LOG_FILE, "w", encoding="utf-8") as log_fh:
        log_fh.write("# CubeCtrl capture -- %s -- %d baud 8N1\n\n" % (datetime.now(), baud))
        rx_buffer = ""
        try:
            while True:
                data = ser.read(ser.in_waiting or 1)
                if data:
                    text = data.decode("ascii", errors="replace")
                    rx_buffer += text
                    while "\n" in rx_buffer:
                        line, rx_buffer = rx_buffer.split("\n", 1)
                        line_clean = clean_line(line.strip())
                        if not line_clean:
                            continue
                        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        decoded = decode_line(line_clean)
                        entry = "[%s] BOX->PC  %s" % (ts, decoded)
                        print(entry)
                        log_fh.write(entry + "\n")
                        log_fh.flush()
        except KeyboardInterrupt:
            print("\n[DONE] Capture stopped.")
        finally:
            ser.close()


# --- MODE 3: PROXY SNIFFER (com0com) -----------------------------------------

def proxy_sniff(baud):
    """
    Full MITM proxy. Requires com0com virtual pair (COM8 <-> COM9).
    Set PortSniffLab to COM8. Bridges COM9 <-> COM7.
    Captures and decodes both directions.
    """
    print("\n[PROXY] Bridging %s (software) <-> %s (box) at %d baud" % (VIRT_SW_PORT, BOX_PORT, baud))
    print("[PROXY] Set PortSniffLab to COM8. Press Ctrl+C to stop.")

    try:
        ser_sw  = serial.Serial(VIRT_SW_PORT, baud, timeout=0.05, **FRAME_FORMAT)
        ser_box = serial.Serial(BOX_PORT,     baud, timeout=0.05, **FRAME_FORMAT)
    except serial.SerialException as e:
        print("[ERROR] %s" % e)
        return

    stop = threading.Event()
    sw_buf = ""
    bx_buf = ""

    with open(LOG_FILE, "w", encoding="utf-8") as log_fh:
        log_fh.write("# CubeCtrl proxy capture -- %s -- %d baud 8N1\n\n" % (datetime.now(), baud))

        def forward(src, dst, direction):
            nonlocal sw_buf, bx_buf
            while not stop.is_set():
                try:
                    data = src.read(src.in_waiting or 1)
                    if data:
                        dst.write(data)
                        text = data.decode("ascii", errors="replace")
                        if direction == "tx":
                            sw_buf += text
                            buf = sw_buf
                        else:
                            bx_buf += text
                            buf = bx_buf

                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            if direction == "tx":
                                sw_buf = buf
                            else:
                                bx_buf = buf
                            line_clean = clean_line(line.strip())
                            if not line_clean:
                                continue
                            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                            arrow = "PC->BOX" if direction == "tx" else "BOX->PC"
                            decoded = decode_line(line_clean)
                            entry = "[%s] %s  %s" % (ts, arrow, decoded)
                            print(entry)
                            log_fh.write(entry + "\n")
                            log_fh.flush()
                except Exception as e:
                    print("[ERROR] %s" % e)
                    stop.set()
                    break

        t1 = threading.Thread(target=forward, args=(ser_sw, ser_box, "tx"), daemon=True)
        t2 = threading.Thread(target=forward, args=(ser_box, ser_sw, "rx"), daemon=True)
        t1.start()
        t2.start()

        print("[OK] Proxy running. Move PortSniffLab sliders to capture commands.\n")
        try:
            while not stop.is_set():
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n[DONE] Stopping proxy.")
            stop.set()

    ser_sw.close()
    ser_box.close()
    print("[DONE] Log saved: %s" % LOG_FILE)


# --- MODE 4: INTERACTIVE CLIENT ----------------------------------------------

def interactive_client(baud):
    """
    Connects to the box, handshakes, then lets you type commands interactively.
    This is the Task 4 deliverable -- drives the box without PortSniffLab.

    Commands you can type:
        hryz <0-359>      -- Set H-Rotation
        vryz <0-359>      -- Set V-Rotation
        hue  <0-359>      -- Set Color Hue
        brt  <0-100>      -- Set Brightness
        zom  <value>      -- Set Zoom
        shp  <name>       -- Set Shape (e.g. Cube_D6)
        raw  <full_cmd>   -- Send any raw string (e.g. raw SET_HRYZ:180)
        quit              -- Exit
    """
    print("\n[CLIENT] Opening %s at %d baud (8N1)" % (BOX_PORT, baud))
    print("[CLIENT] Python-only controller -- no PortSniffLab needed.\n")

    try:
        ser = serial.Serial(BOX_PORT, baud, timeout=0.1, **FRAME_FORMAT)
    except serial.SerialException as e:
        print("[ERROR] Cannot open %s: %s" % (BOX_PORT, e))
        return

    with open(LOG_FILE, "w", encoding="utf-8") as log_fh:
        log_fh.write("# CubeCtrl client session -- %s -- %d baud 8N1\n\n" % (datetime.now(), baud))

        print("[CLIENT] Waiting for CUBECTRL:READY broadcast (up to 5s)...")
        deadline = time.time() + 5.0
        got_ready = False
        rx_buf = ""
        while time.time() < deadline:
            data = ser.read(ser.in_waiting or 1)
            if data:
                rx_buf += data.decode("ascii", errors="replace")
                if "CUBECTRL:READY" in rx_buf:
                    for line in rx_buf.splitlines():
                        if "CUBECTRL:READY" in line:
                            print("[CLIENT] Box alive: %s" % clean_line(line.strip()))
                            got_ready = True
                            break
                    break

        if not got_ready:
            print("[CLIENT] No READY received -- trying handshake anyway...")

        if not do_handshake(ser, log_fh):
            ser.close()
            return

        ALIAS = {
            "hryz": ("SET_HRYZ", 0, 359),
            "vryz": ("SET_VRYZ", 0, 359),
            "hue":  ("SET_HUE",  0, 359),
            "brt":  ("SET_BRT",  0, 100),
            "zom":  ("SET_ZOM",  None, None),
        }

        print("=" * 60)
        print("  INTERACTIVE CLIENT -- type commands below")
        print("  Examples:")
        print("    hryz 90        -> SET_HRYZ:090")
        print("    brt 50         -> SET_BRT:050")
        print("    shp Tetra_D4   -> SET_SHP:Tetra_D4")
        print("  Shape options: %s" % ", ".join(KNOWN_SHAPES))
        print("    raw SET_HRYZ:180   (send any raw string)")
        print("    quit")
        print("=" * 60)

        try:
            while True:
                try:
                    user_input = input("\nCMD> ").strip()
                except EOFError:
                    break

                if not user_input:
                    continue

                parts = user_input.split(None, 1)
                verb = parts[0].lower()
                arg  = parts[1] if len(parts) > 1 else ""

                if verb == "quit":
                    break

                elif verb == "raw":
                    send_command(ser, arg, log_fh)

                elif verb == "shp":
                    if not arg:
                        print("  Shapes: %s" % ", ".join(KNOWN_SHAPES))
                    else:
                        send_command(ser, "SET_SHP:%s" % arg, log_fh)

                elif verb in ALIAS:
                    cmd_prefix, lo, hi = ALIAS[verb]
                    if not arg:
                        range_str = "%d-%d" % (lo, hi) if lo is not None else "any"
                        print("  Usage: %s <%s>" % (verb, range_str))
                        continue
                    try:
                        val = int(arg)
                        if lo is not None and not (lo <= val <= hi):
                            print("  [WARN] %d is outside [%d, %d]" % (val, lo, hi))
                        send_command(ser, "%s:%03d" % (cmd_prefix, val), log_fh)
                    except ValueError:
                        print("  [ERROR] '%s' is not a number." % arg)

                else:
                    print("  Unknown command '%s'. Try: hryz vryz hue brt zom shp raw quit" % verb)

        except KeyboardInterrupt:
            print("\n[CLIENT] Interrupted.")
        finally:
            ser.close()

    print("\n[DONE] Session log saved: %s" % LOG_FILE)


# --- MODE 5: AUTO DEMO -------------------------------------------------------

def auto_demo(baud):
    """
    Automatically sends all 5 SET_ commands with representative values and
    logs every DRW_ echo with round-trip timing. Good for Task 2 evidence.
    """
    print("\n[DEMO] Auto-sweep all parameters at %d baud" % baud)

    try:
        ser = serial.Serial(BOX_PORT, baud, timeout=0.1, **FRAME_FORMAT)
    except serial.SerialException as e:
        print("[ERROR] Cannot open %s: %s" % (BOX_PORT, e))
        return

    with open(LOG_FILE, "w", encoding="utf-8") as log_fh:
        log_fh.write("# CubeCtrl auto-demo -- %s -- %d baud 8N1\n\n" % (datetime.now(), baud))

        print("[DEMO] Waiting for CUBECTRL:READY ...")
        deadline = time.time() + 5.0
        rx_buf = ""
        while time.time() < deadline:
            d = ser.read(ser.in_waiting or 1)
            if d:
                rx_buf += d.decode("ascii", errors="replace")
                if "CUBECTRL:READY" in rx_buf:
                    print("[DEMO] Box is ready.")
                    break

        if not do_handshake(ser, log_fh):
            ser.close()
            return

        sweep = [
            ("SET_HRYZ", [0, 45, 90, 135, 180, 270, 359]),
            ("SET_VRYZ", [0, 45, 90, 180, 270, 359]),
            ("SET_HUE",  [0, 60, 120, 180, 240, 300]),
            ("SET_BRT",  [20, 56, 92, 128, 164, 200]),
            ("SET_ZOM",  [50, 100, 150, 200, 250, 300]),
        ]

        for cmd_prefix, values in sweep:
            print("\n-- Sweeping %s --" % cmd_prefix)
            for val in values:
                t0 = time.time()
                reply = send_command(ser, "%s:%03d" % (cmd_prefix, val), log_fh)
                latency_ms = (time.time() - t0) * 1000
                status = "OK" if reply else "TIMEOUT"
                print("   %s:%03d -> %-20s  [%.1f ms] %s" % (cmd_prefix, val, reply or "(no echo)", latency_ms, status))
                time.sleep(0.1)

        print("\n-- Sweeping SET_SHP --")
        for shape in KNOWN_SHAPES:
            t0 = time.time()
            reply = send_command(ser, "SET_SHP:%s" % shape, log_fh)
            latency_ms = (time.time() - t0) * 1000
            status = "OK" if reply else "TIMEOUT"
            print("   SET_SHP:%-12s -> %-20s  [%.1f ms] %s" % (shape, reply or "(no echo)", latency_ms, status))
            time.sleep(0.2)

    ser.close()
    print("\n[DONE] Auto-demo complete. Log saved: %s" % LOG_FILE)


# --- MODE 6: DECODE A LOG FILE -----------------------------------------------

def decode_log(filepath):
    """Re-parse a saved log file and print decoded output."""
    if not os.path.exists(filepath):
        print("[ERROR] File not found: %s" % filepath)
        return
    print("\n[DECODE] Parsing: %s\n" % filepath)
    print("%-15s %-10s %-25s %s" % ("Timestamp", "Dir", "Meaning", "Raw"))
    print("-" * 80)
    with open(filepath, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            print(line)


# --- ENTRY POINT -------------------------------------------------------------

HELP = """
PH585 PortSniffLab -- CubeCtrl Probe + Client

Usage:
  python MysteryBlackBoxProbe.py detect              -- Find baud rate (close PortSniffLab first)
  python MysteryBlackBoxProbe.py direct [baud]       -- Passive read-only tap (close PortSniffLab)
  python MysteryBlackBoxProbe.py sniff  [baud]       -- MITM proxy (needs com0com, PortSniffLab on COM8)
  python MysteryBlackBoxProbe.py client [baud]       -- Interactive Python client (Task 4)
  python MysteryBlackBoxProbe.py demo   [baud]       -- Auto-sweep all parameters (Task 2 evidence)
  python MysteryBlackBoxProbe.py decode <file>       -- Decode a saved .log file

Recommended workflow:
  1. Close PortSniffLab
  2. python MysteryBlackBoxProbe.py detect
  3. python MysteryBlackBoxProbe.py direct 115200
  4. Reopen PortSniffLab, install com0com, run sniff for bidirectional capture
  5. python MysteryBlackBoxProbe.py client 115200    (Task 4 -- your own controller)
  6. python MysteryBlackBoxProbe.py demo   115200    (Task 2 -- timed sweep)
"""

if __name__ == "__main__":
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "help"

    if mode == "detect":
        detect_baud()

    elif mode == "direct":
        baud = int(sys.argv[2]) if len(sys.argv) > 2 else None
        if baud is None:
            baud = detect_baud()
        if baud:
            direct_sniff(baud)

    elif mode == "sniff":
        baud = int(sys.argv[2]) if len(sys.argv) > 2 else None
        if baud is None:
            print("[INFO] Specify baud: python MysteryBlackBoxProbe.py sniff 115200")
        else:
            proxy_sniff(baud)

    elif mode == "client":
        baud = int(sys.argv[2]) if len(sys.argv) > 2 else None
        if baud is None:
            baud = detect_baud()
        if baud:
            interactive_client(baud)

    elif mode == "demo":
        baud = int(sys.argv[2]) if len(sys.argv) > 2 else None
        if baud is None:
            baud = detect_baud()
        if baud:
            auto_demo(baud)

    elif mode == "decode":
        if len(sys.argv) < 3:
            print("[ERROR] Provide a log file path: python MysteryBlackBoxProbe.py decode capture.log")
        else:
            decode_log(sys.argv[2])

    else:
        print(HELP)