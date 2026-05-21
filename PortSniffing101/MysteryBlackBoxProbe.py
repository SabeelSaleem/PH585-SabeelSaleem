"""
PH585 -- CubeCtrl Visual Client (Closed-Loop)
=============================================
Modern single-window GUI client for the Arduino Nano + MAX3232 mystery box.

Two functions:
  1. Auto-detect the (randomized) baud rate by listening for the
     CUBECTRL:READY:<baud> broadcast that the firmware emits every ~2s.
  2. A closed-loop visual interface -- sliders send SET_ commands to the
     box, and the integrated 3D viewport only updates when the box sends
     back a confirming DRW_ reply. The renderer NEVER draws speculatively:
     the image you see is exactly the state the hardware reports.

Protocol (reverse-engineered from Wireshark + USBPcap capture):
    Boot broadcast (every 2s):    CUBECTRL:READY:<baudrate>
    Connect handshake (best-effort): CUBECTRL:CONNECT
    Disconnect (PC->BOX, echoed): CUBECTRL:DISCONNECT

    Commands (PC->BOX -> input echo + DRW_ response):
        SET_HRYZ:<000-359>  ->  DRW_HRYZ:<val>    H-Rotation (Y axis)
        SET_VERT:<000-359>  ->  DRW_VERT:<val>    V-Rotation (X axis)
        SET_COLR:<000-359>  ->  DRW_COLR:<val>    Color (HSV hue)
        SET_ZOOM:<050-300>  ->  DRW_ZOOM:<val>    Zoom (scale x100)
        SET_SHPE:<NAME>     ->  DRW_SHPE:<NAME>   Shape (dice)

    Shape (dice) names: CUBE, SPHER, TETRA, OCTO, DODEC, ICOSA

    Brightness has NO box command -- the original PortSniffLab applied it
    locally as a render-only setting. The slider here is treated the same
    way: it updates the renderer state directly, with no serial traffic.

    All lines terminated with \\r\\n. Numeric values zero-padded to 3 digits.

REQUIRES:
    pip install pyserial PyOpenGL pyopengltk
    (tkinter ships with Python on Windows)

RUN:
    python MysteryBlackBoxProbe.py
"""

import math
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, scrolledtext, ttk

import serial
import serial.tools.list_ports

try:
    from OpenGL.GL import (
        glClear, glClearColor, glEnable, glDisable, glMatrixMode,
        glLoadIdentity, glTranslatef, glRotatef, glScalef, glBegin, glEnd,
        glVertex3f, glColor3f, glColor4f, glNormal3f, glLineWidth,
        glPolygonOffset, glViewport, glLightfv, glColorMaterial, glHint,
        glShadeModel, glBlendFunc, glDepthMask, glPushMatrix, glPopMatrix,
        glMaterialfv, glMaterialf,
        GL_TRIANGLE_FAN, GL_LINE_LOOP, GL_DEPTH_TEST,
        GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_PROJECTION,
        GL_MODELVIEW, GL_LIGHTING, GL_LIGHT0, GL_POSITION, GL_DIFFUSE,
        GL_AMBIENT, GL_SPECULAR, GL_SHININESS, GL_EMISSION,
        GL_COLOR_MATERIAL, GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE,
        GL_POLYGON_OFFSET_FILL, GL_LINE_SMOOTH, GL_LINE_SMOOTH_HINT,
        GL_NICEST, GL_SMOOTH, GL_BLEND,
        GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_TRUE, GL_FALSE,
    )
    from OpenGL.GLU import gluPerspective
    from pyopengltk import OpenGLFrame
    HAS_OPENGL = True
    _OPENGL_ERR = None
except ImportError as _e:
    HAS_OPENGL = False
    _OPENGL_ERR = str(_e)
    OpenGLFrame = object


# ---------------------------------------------------------------------------
# Theme  (modern dark accent palette)
# ---------------------------------------------------------------------------

THEME = {
    "bg":            "#0f1419",   # window background
    "panel":         "#1a1f2e",   # card / panel background
    "panel_lt":      "#242938",   # slightly lighter for inputs
    "border":        "#2a3142",
    "text":          "#e6e8ec",   # primary text
    "text_dim":      "#8b92a5",   # secondary text
    "text_mute":     "#5c6478",   # tertiary / hints
    "accent":        "#5b8def",   # primary accent (blue)
    "accent_hi":     "#7aa3ff",
    "accent_dark":   "#3a6ad4",
    "success":       "#3ddc97",   # connected
    "warn":          "#f5b042",   # detecting
    "danger":        "#ef5e6e",   # disconnected / error
    "tx":            "#5b8def",   # log: PC -> BOX
    "rx":            "#3ddc97",   # log: BOX -> PC
    "sys":           "#8b92a5",   # log: system
    "err":           "#ef5e6e",   # log: error
    "render_bg":     "#0a0d12",   # 3D viewport clear color (slightly darker)
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_PORT = "COM7"
BAUD_RATES   = [9600, 19200, 38400, 57600, 115200]
FRAME_FORMAT = dict(
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
)
DETECT_TIMEOUT_PER_BAUD = 5.0


# Dice labels: (protocol_name, display_label, face_count)
DICE_SHAPES = [
    ("CUBE",  "Cube",         6),
    ("SPHER", "Sphere",       1),
    ("TETRA", "Tetrahedron",  4),
    ("OCTO",  "Octahedron",   8),
    ("DODEC", "Dodecahedron", 12),
    ("ICOSA", "Icosahedron",  20),
]
DICE_DISPLAY = [f"{lbl}  (D{n})" for _, lbl, n in DICE_SHAPES]
DICE_DISPLAY_TO_PROTO = {f"{lbl}  (D{n})": proto for proto, lbl, n in DICE_SHAPES}
DICE_PROTO_TO_DISPLAY = {proto: f"{lbl}  (D{n})" for proto, lbl, n in DICE_SHAPES}


COMMAND_LABELS = {
    "SET_HRYZ":  "H-Rotation",
    "SET_VERT":  "V-Rotation",
    "SET_COLR":  "Color",
    "SET_ZOOM":  "Zoom",
    "SET_SHPE":  "Shape",
    "DRW_HRYZ":  "Echo H-Rot",
    "DRW_VERT":  "Echo V-Rot",
    "DRW_COLR":  "Echo Color",
    "DRW_ZOOM":  "Echo Zoom",
    "DRW_SHPE":  "Echo Shape",
    "CUBECTRL":  "Handshake",
    "ACK_CONN":  "Connect ACK",
}


# Defaults (initial state pushed to box on connect; renderer waits for DRW_ echo)
DEFAULTS = {
    "HRYZ": 180,
    "VERT": 180,
    "COLR": 180,
    "ZOOM": 100,
    "BRT":  100,       # local-only; renderer reads this directly
    "SHPE": "CUBE",
}


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def clean_line(raw: str) -> str:
    return "".join(c for c in raw if 32 <= ord(c) < 127).strip()


def label_for(line: str) -> str:
    for prefix, lab in COMMAND_LABELS.items():
        if line.startswith(prefix):
            return lab
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Baud auto-detect
# ---------------------------------------------------------------------------

def detect_baud(port, status_cb=None, stop_event=None):
    def say(msg):
        if status_cb:
            status_cb(msg)
        else:
            print(msg)

    say(f"=== Baud Auto-Detection on {port} ===")
    for baud in BAUD_RATES:
        if stop_event is not None and stop_event.is_set():
            say("Detection cancelled.")
            return None
        say(f"[..] Trying {baud} baud ...")
        try:
            ser = serial.Serial(port, baud, timeout=0.5, **FRAME_FORMAT)
        except serial.SerialException as e:
            say(f"[ERROR] Could not open {port}: {e}")
            return None
        try:
            deadline = time.time() + DETECT_TIMEOUT_PER_BAUD
            buf = ""
            while time.time() < deadline:
                if stop_event is not None and stop_event.is_set():
                    say("Detection cancelled.")
                    return None
                chunk = ser.read(64).decode("ascii", errors="replace")
                if chunk:
                    buf += chunk
                    if "CUBECTRL:READY" in buf:
                        for line in buf.splitlines():
                            cl = clean_line(line)
                            if "CUBECTRL:READY" in cl:
                                parts = cl.split(":")
                                embedded = parts[-1] if len(parts) >= 3 else "?"
                                say(f"     FOUND at {baud} baud!")
                                say(f"     Raw:           {cl}")
                                say(f"     Embedded baud: {embedded}")
                                return baud
        finally:
            ser.close()

    say("No CUBECTRL:READY received at any baud rate.")
    say("Check: Is the box powered on? Is COM port correct? Is anything else holding it open?")
    return None


# ---------------------------------------------------------------------------
# Shape meshes
# ---------------------------------------------------------------------------

PHI = (1 + math.sqrt(5)) / 2


def _normalize_to_unit(verts):
    r = max(math.sqrt(x*x + y*y + z*z) for x, y, z in verts) or 1.0
    return [(x/r, y/r, z/r) for x, y, z in verts]


def make_cube():
    v = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [
        [4, 5, 7, 6], [0, 2, 3, 1],
        [2, 6, 7, 3], [0, 1, 5, 4],
        [1, 3, 7, 5], [0, 4, 6, 2],
    ]
    return _normalize_to_unit(v), faces


def make_tetrahedron():
    v = [(1, 1, 1), (-1, -1, 1), (-1, 1, -1), (1, -1, -1)]
    faces = [[0, 1, 2], [0, 3, 1], [0, 2, 3], [1, 3, 2]]
    return _normalize_to_unit(v), faces


def make_octahedron():
    v = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
    faces = [
        [0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4],
        [2, 0, 5], [1, 2, 5], [3, 1, 5], [0, 3, 5],
    ]
    return _normalize_to_unit(v), faces


def make_icosahedron():
    a, b = 1.0, PHI
    v = [
        (0,  a,  b), (0, -a,  b), (0,  a, -b), (0, -a, -b),
        (a,  b,  0), (-a,  b,  0), (a, -b,  0), (-a, -b,  0),
        (b,  0,  a), (-b,  0,  a), (b,  0, -a), (-b,  0, -a),
    ]
    faces = [
        [0, 1, 8],  [0, 8, 4],  [0, 4, 5],  [0, 5, 9],  [0, 9, 1],
        [1, 9, 7],  [1, 7, 6],  [1, 6, 8],  [8, 6, 10], [8, 10, 4],
        [4, 10, 2], [4, 2, 5],  [5, 2, 11], [5, 11, 9], [9, 11, 7],
        [3, 6, 7],  [3, 7, 11], [3, 11, 2], [3, 2, 10], [3, 10, 6],
    ]
    return _normalize_to_unit(v), faces


def make_dodecahedron():
    b, c = 1/PHI, PHI
    v = [
        ( 1,  1,  1), ( 1,  1, -1), ( 1, -1,  1), ( 1, -1, -1),
        (-1,  1,  1), (-1,  1, -1), (-1, -1,  1), (-1, -1, -1),
        (0,  b,  c), (0,  b, -c), (0, -b,  c), (0, -b, -c),
        ( b,  c, 0), ( b, -c, 0), (-b,  c, 0), (-b, -c, 0),
        ( c, 0,  b), ( c, 0, -b), (-c, 0,  b), (-c, 0, -b),
    ]
    faces = [
        [0,  8, 10,  2, 16], [0, 16, 17,  1, 12], [0, 12, 14,  4,  8],
        [1, 17,  3, 11,  9], [1,  9,  5, 14, 12], [2, 10,  6, 15, 13],
        [2, 13,  3, 17, 16], [3, 13, 15,  7, 11], [4, 14,  5, 19, 18],
        [4, 18,  6, 10,  8], [5,  9, 11,  7, 19], [6, 18, 19,  7, 15],
    ]
    return _normalize_to_unit(v), faces


def make_sphere(stacks=20, slices=30):
    verts = []
    for i in range(stacks + 1):
        theta = math.pi * i / stacks
        for j in range(slices):
            phi = 2 * math.pi * j / slices
            verts.append((
                math.sin(theta) * math.cos(phi),
                math.cos(theta),
                math.sin(theta) * math.sin(phi),
            ))
    faces = []
    for i in range(stacks):
        for j in range(slices):
            j2 = (j + 1) % slices
            a = i * slices + j
            b_ = i * slices + j2
            c_ = (i + 1) * slices + j
            d_ = (i + 1) * slices + j2
            faces.append([a, b_, d_, c_])
    return verts, faces


SHAPE_BUILDERS = {
    "CUBE":  make_cube,
    "SPHER": make_sphere,
    "TETRA": make_tetrahedron,
    "OCTO":  make_octahedron,
    "DODEC": make_dodecahedron,
    "ICOSA": make_icosahedron,
}


def face_normal(verts, face):
    n = len(face)
    cx = sum(verts[i][0] for i in face) / n
    cy = sum(verts[i][1] for i in face) / n
    cz = sum(verts[i][2] for i in face) / n
    for offset in range(n):
        p0 = verts[face[offset]]
        p1 = verts[face[(offset + 1) % n]]
        p2 = verts[face[(offset + 2) % n]]
        e1 = (p1[0]-p0[0], p1[1]-p0[1], p1[2]-p0[2])
        e2 = (p2[0]-p0[0], p2[1]-p0[1], p2[2]-p0[2])
        nx = e1[1]*e2[2] - e1[2]*e2[1]
        ny = e1[2]*e2[0] - e1[0]*e2[2]
        nz = e1[0]*e2[1] - e1[1]*e2[0]
        mag = math.sqrt(nx*nx + ny*ny + nz*nz)
        if mag > 1e-9:
            nx, ny, nz = nx/mag, ny/mag, nz/mag
            if nx*cx + ny*cy + nz*cz < 0:
                nx, ny, nz = -nx, -ny, -nz
            return nx, ny, nz
    cmag = math.sqrt(cx*cx + cy*cy + cz*cz) or 1.0
    return cx/cmag, cy/cmag, cz/cmag


def hsv_to_rgb(h, s, v):
    if s <= 0.0:
        return v, v, v
    h = h % 1.0
    i = int(h * 6)
    f = h * 6 - i
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))
    return [(v, t, p), (q, v, p), (p, v, t),
            (p, q, v), (t, p, v), (v, p, q)][i % 6]


# ---------------------------------------------------------------------------
# 3D Renderer (closed-loop: reads CONFIRMED state, never the live sliders)
# ---------------------------------------------------------------------------

if HAS_OPENGL:

    class RenderFrame(OpenGLFrame):
        """
        Reads the *confirmed* state dict (last DRW_ values from the box).
        If confirmed_state["shape"] is None, the viewport stays blank --
        nothing is drawn until the hardware reports its state.
        """
        def __init__(self, master, confirmed_state, **kwargs):
            super().__init__(master, **kwargs)
            self.confirmed_state = confirmed_state
            self._mesh_cache = {}

        def initgl(self):
            glEnable(GL_DEPTH_TEST)
            glEnable(GL_LINE_SMOOTH)
            glHint(GL_LINE_SMOOTH_HINT, GL_NICEST)
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glShadeModel(GL_SMOOTH)
            r, g, b = self._hex_to_rgb(THEME["render_bg"])
            glClearColor(r, g, b, 1.0)

        @staticmethod
        def _hex_to_rgb(hexstr):
            h = hexstr.lstrip("#")
            return int(h[0:2], 16)/255.0, int(h[2:4], 16)/255.0, int(h[4:6], 16)/255.0

        def redraw(self):
            cs = self.confirmed_state
            glViewport(0, 0, self.width, self.height)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

            shape = cs.get("shape")
            if shape is None:
                # No confirmed state from box -- draw nothing.
                return

            verts, faces = self._get_mesh(shape)

            # ---- Camera ----
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            aspect = self.width / max(self.height, 1)
            gluPerspective(38.0, aspect, 0.1, 100.0)

            glMatrixMode(GL_MODELVIEW)
            glLoadIdentity()
            glTranslatef(0.0, 0.0, -5.0)

            # ---- Compute base color and brightness ----
            r, g, b = hsv_to_rgb(cs["COLR"] / 360.0, 0.82, 1.0)
            bf = cs["BRT"] / 100.0
            sr = min(1.0, r * bf); sg = min(1.0, g * bf); sb = min(1.0, b * bf)

            # ---- Object transform ----
            # Push the transform so each pass starts from the same camera frame
            glPushMatrix()
            glRotatef(cs["VERT"], 1.0, 0.0, 0.0)
            glRotatef(cs["HRYZ"], 0.0, 1.0, 0.0)
            scale = cs["ZOOM"] / 100.0
            glScalef(scale, scale, scale)

            # =====================================================
            # PASS 1: smooth halo glow (additive, behind solid object)
            # =====================================================
            # 22 thin shells, exponentially falling alpha. With this many
            # layers the steps are smaller than one pixel of opacity change
            # per shell -- visually continuous, no banding.
            #
            # The innermost shell starts at expansion 1.002 (basically ON
            # the surface) so the glow appears to emanate FROM the object,
            # not from an offset ring around it.
            glDisable(GL_LIGHTING)
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE)   # additive
            glDepthMask(GL_FALSE)
            glDisable(GL_POLYGON_OFFSET_FILL)

            N_HALO = 22
            EXPAND_MIN = 1.002
            EXPAND_MAX = 1.65
            BASE_ALPHA = 0.085
            DECAY      = 3.2

            glow_intensity = min(1.0, 0.55 + 0.45 * bf)
            for i in range(N_HALO):
                t = i / (N_HALO - 1)             # 0..1
                expand = EXPAND_MIN + (EXPAND_MAX - EXPAND_MIN) * t
                # Exponential falloff, smooth and unbanded
                alpha = BASE_ALPHA * math.exp(-DECAY * t) * glow_intensity
                glColor4f(sr, sg, sb, alpha)
                glPushMatrix()
                glScalef(expand, expand, expand)
                for face in faces:
                    glBegin(GL_TRIANGLE_FAN)
                    for idx in face:
                        glVertex3f(*verts[idx])
                    glEnd()
                glPopMatrix()

            glDepthMask(GL_TRUE)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

            # =====================================================
            # PASS 2: solid lit shape with EMISSION (self-illuminated)
            # =====================================================
            # Emission makes the object's own surface glow with its base
            # color independent of scene lighting. This is what sells the
            # "the object itself is glowing" look -- it's bright on every
            # face, not just the lit side, and the halo around it is just
            # the light bleeding outward.
            glEnable(GL_LIGHTING)
            glEnable(GL_LIGHT0)
            glLightfv(GL_LIGHT0, GL_POSITION, [0.6, 1.2, 1.8, 0.0])
            glLightfv(GL_LIGHT0, GL_DIFFUSE,  [0.85, 0.85, 0.85, 1.0])
            glLightfv(GL_LIGHT0, GL_AMBIENT,  [0.30, 0.32, 0.38, 1.0])
            glLightfv(GL_LIGHT0, GL_SPECULAR, [0.95, 0.95, 0.95, 1.0])
            glEnable(GL_COLOR_MATERIAL)
            glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)

            # Emission strength scales with brightness so dim objects glow dimly.
            em = 0.55 * bf
            emission = [min(1.0, sr * em),
                        min(1.0, sg * em),
                        min(1.0, sb * em), 1.0]
            glMaterialfv(GL_FRONT_AND_BACK, GL_EMISSION, emission)

            spec = [0.7 * bf, 0.7 * bf, 0.7 * bf, 1.0]
            glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, spec)
            glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, 56.0)

            glEnable(GL_POLYGON_OFFSET_FILL)
            glPolygonOffset(1.0, 1.0)
            glColor3f(sr, sg, sb)
            for face in faces:
                nx, ny, nz = face_normal(verts, face)
                glBegin(GL_TRIANGLE_FAN)
                glNormal3f(nx, ny, nz)
                for idx in face:
                    glVertex3f(*verts[idx])
                glEnd()
            glDisable(GL_POLYGON_OFFSET_FILL)

            # Reset material so emission/specular don't bleed into wireframe
            glMaterialfv(GL_FRONT_AND_BACK, GL_EMISSION, [0.0, 0.0, 0.0, 1.0])
            glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, [0.0, 0.0, 0.0, 1.0])

            # =====================================================
            # PASS 3: wireframe overlay (subtle, kept dim near the glow)
            # =====================================================
            glDisable(GL_LIGHTING)
            edge = max(0.08, min(0.35, 0.25 * bf))
            glColor4f(edge, edge, edge, 0.85)
            glLineWidth(1.4)
            for face in faces:
                glBegin(GL_LINE_LOOP)
                for idx in face:
                    glVertex3f(*verts[idx])
                glEnd()

            glPopMatrix()

        def _get_mesh(self, shape_name):
            if shape_name not in self._mesh_cache:
                builder = SHAPE_BUILDERS.get(shape_name, make_cube)
                self._mesh_cache[shape_name] = builder()
            return self._mesh_cache[shape_name]


# ---------------------------------------------------------------------------
# Custom modern slider widget (canvas-based; matches dark theme)
# ---------------------------------------------------------------------------

class ModernSlider(tk.Canvas):
    """
    Horizontal slider with theme-aware rendering. Emits two callbacks:
      on_change(value)        -- called on every drag step (live value)
      on_release(value)       -- called when user releases the mouse
    """
    TRACK_H = 4
    KNOB_R  = 9

    def __init__(self, master, lo, hi, default, on_change=None, on_release=None,
                 width=320, height=28, **kwargs):
        super().__init__(master, width=width, height=height,
                         bg=THEME["panel"], highlightthickness=0, **kwargs)
        self.lo = lo
        self.hi = hi
        self.value = default
        self.on_change = on_change
        self.on_release = on_release
        self.w = width
        self.h = height
        self._dragging = False
        self._enabled = True

        self.bind("<Configure>",       self._on_configure)
        self.bind("<Button-1>",        self._on_press)
        self.bind("<B1-Motion>",       self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_up)
        self._redraw()

    def _on_configure(self, _e):
        self.w = self.winfo_width() or self.w
        self.h = self.winfo_height() or self.h
        self._redraw()

    def set_value(self, v, fire_callbacks=False):
        v = max(self.lo, min(self.hi, int(v)))
        if v != self.value:
            self.value = v
            self._redraw()
            if fire_callbacks and self.on_change:
                self.on_change(self.value)

    def get_value(self):
        return self.value

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        self._redraw()

    def _value_to_x(self, v):
        pad = self.KNOB_R + 2
        usable = max(1, self.w - 2 * pad)
        return pad + (v - self.lo) / (self.hi - self.lo) * usable

    def _x_to_value(self, x):
        pad = self.KNOB_R + 2
        usable = max(1, self.w - 2 * pad)
        frac = (x - pad) / usable
        frac = max(0.0, min(1.0, frac))
        return round(self.lo + frac * (self.hi - self.lo))

    def _redraw(self):
        self.delete("all")
        cy = self.h // 2
        pad = self.KNOB_R + 2
        x_right = self.w - pad
        x_knob = self._value_to_x(self.value)

        track_color = THEME["panel_lt"] if self._enabled else "#1d2230"
        fill_color  = THEME["accent"]   if self._enabled else "#3a4256"
        knob_outer  = THEME["accent_hi"] if self._enabled else "#4a5468"
        knob_inner  = THEME["text"]     if self._enabled else "#7a8294"

        # Track (rounded by drawing oval caps + rect)
        self.create_rectangle(pad, cy - self.TRACK_H//2,
                              x_right, cy + self.TRACK_H//2,
                              fill=track_color, outline="")
        self.create_oval(pad - self.TRACK_H//2, cy - self.TRACK_H//2,
                         pad + self.TRACK_H//2, cy + self.TRACK_H//2,
                         fill=track_color, outline="")
        self.create_oval(x_right - self.TRACK_H//2, cy - self.TRACK_H//2,
                         x_right + self.TRACK_H//2, cy + self.TRACK_H//2,
                         fill=track_color, outline="")

        # Filled portion
        if x_knob > pad:
            self.create_rectangle(pad, cy - self.TRACK_H//2,
                                  x_knob, cy + self.TRACK_H//2,
                                  fill=fill_color, outline="")
            self.create_oval(pad - self.TRACK_H//2, cy - self.TRACK_H//2,
                             pad + self.TRACK_H//2, cy + self.TRACK_H//2,
                             fill=fill_color, outline="")

        # Knob (subtle outer ring + inner dot)
        r = self.KNOB_R
        self.create_oval(x_knob - r, cy - r, x_knob + r, cy + r,
                         fill=knob_outer, outline="")
        self.create_oval(x_knob - r + 2, cy - r + 2,
                         x_knob + r - 2, cy + r - 2,
                         fill=knob_inner, outline="")

    def _on_press(self, e):
        if not self._enabled:
            return
        self._dragging = True
        new_v = self._x_to_value(e.x)
        if new_v != self.value:
            self.value = new_v
            self._redraw()
            if self.on_change:
                self.on_change(self.value)

    def _on_drag(self, e):
        if not self._enabled or not self._dragging:
            return
        new_v = self._x_to_value(e.x)
        if new_v != self.value:
            self.value = new_v
            self._redraw()
            if self.on_change:
                self.on_change(self.value)

    def _on_up(self, _e):
        if not self._enabled:
            return
        self._dragging = False
        if self.on_release:
            self.on_release(self.value)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class CubeCtrlApp:

    def __init__(self, root):
        self.root = root
        self.root.title("CubeCtrl  ·  PH585 PortSniffLab Client")
        self.root.geometry("1280x780")
        self.root.minsize(1100, 420)
        self.root.configure(bg=THEME["bg"])

        # Serial state
        self.ser = None
        self.reader_thread = None
        self.reader_stop = threading.Event()
        self.detect_stop = threading.Event()
        self.detect_thread = None

        # Thread-safe message queue (worker -> GUI)
        self.gui_queue = queue.Queue()

        # CONFIRMED state -- only updated from incoming DRW_ messages.
        # While shape is None the renderer draws nothing.
        self.confirmed = {
            "HRYZ": 0, "VERT": 0, "COLR": 0, "ZOOM": 100,
            "BRT":  DEFAULTS["BRT"],
            "shape": None,
        }
        # Outbound pending tracker (purely informational; not required)
        self.pending = {}

        # Slider widget refs (filled by _build_ui)
        self.sliders = {}
        self.value_labels = {}

        self._configure_styles()
        self._build_ui()
        self._poll_queue()
        self._refresh_ports()

    # ===== Styling =========================================================

    def _configure_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")     # clam is the most customizable built-in theme
        except tk.TclError:
            pass

        # Frames
        style.configure("App.TFrame",        background=THEME["bg"])
        style.configure("Panel.TFrame",      background=THEME["panel"])
        style.configure("PanelDark.TFrame",  background=THEME["bg"])

        # Labels
        style.configure("App.TLabel",
                        background=THEME["bg"], foreground=THEME["text"],
                        font=("Segoe UI", 10))
        style.configure("Panel.TLabel",
                        background=THEME["panel"], foreground=THEME["text"],
                        font=("Segoe UI", 10))
        style.configure("PanelDim.TLabel",
                        background=THEME["panel"], foreground=THEME["text_dim"],
                        font=("Segoe UI", 9))
        style.configure("PanelMute.TLabel",
                        background=THEME["panel"], foreground=THEME["text_mute"],
                        font=("Segoe UI", 9))
        style.configure("Heading.TLabel",
                        background=THEME["panel"], foreground=THEME["text"],
                        font=("Segoe UI Semibold", 11))
        style.configure("Title.TLabel",
                        background=THEME["bg"], foreground=THEME["text"],
                        font=("Segoe UI Semibold", 16))
        style.configure("Subtitle.TLabel",
                        background=THEME["bg"], foreground=THEME["text_dim"],
                        font=("Segoe UI", 9))
        style.configure("Value.TLabel",
                        background=THEME["panel"], foreground=THEME["accent_hi"],
                        font=("Consolas", 11))
        style.configure("Status.TLabel",
                        background=THEME["panel"], foreground=THEME["danger"],
                        font=("Segoe UI Semibold", 10))

        # Buttons (primary accent)
        style.configure("Primary.TButton",
                        background=THEME["accent"], foreground="#ffffff",
                        font=("Segoe UI Semibold", 10),
                        borderwidth=0, focusthickness=0,
                        padding=(14, 7))
        style.map("Primary.TButton",
                  background=[("active",   THEME["accent_hi"]),
                              ("disabled", "#2a3142")],
                  foreground=[("disabled", "#5c6478")])

        # Buttons (secondary outline)
        style.configure("Secondary.TButton",
                        background=THEME["panel_lt"], foreground=THEME["text"],
                        font=("Segoe UI", 10),
                        borderwidth=0, focusthickness=0,
                        padding=(12, 6))
        style.map("Secondary.TButton",
                  background=[("active",   "#2e3548"),
                              ("disabled", "#1d2230")],
                  foreground=[("disabled", "#5c6478")])

        # Combobox & Entry
        style.configure("Modern.TCombobox",
                        fieldbackground=THEME["panel_lt"],
                        background=THEME["panel_lt"],
                        foreground=THEME["text"],
                        bordercolor=THEME["border"],
                        lightcolor=THEME["border"],
                        darkcolor=THEME["border"],
                        arrowcolor=THEME["text_dim"],
                        selectbackground=THEME["accent"],
                        selectforeground="#ffffff",
                        padding=4)
        style.map("Modern.TCombobox",
                  fieldbackground=[("readonly", THEME["panel_lt"]),
                                   ("disabled", "#1d2230")],
                  foreground=[("disabled", "#5c6478")],
                  bordercolor=[("focus", THEME["accent"])])
        # Dropdown listbox colors (root-level option DB)
        self.root.option_add("*TCombobox*Listbox.background", THEME["panel_lt"])
        self.root.option_add("*TCombobox*Listbox.foreground", THEME["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", THEME["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.root.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))
        self.root.option_add("*TCombobox*Listbox.borderWidth", 0)

        style.configure("Modern.TEntry",
                        fieldbackground=THEME["panel_lt"],
                        foreground=THEME["text"],
                        bordercolor=THEME["border"],
                        lightcolor=THEME["border"],
                        darkcolor=THEME["border"],
                        insertcolor=THEME["text"],
                        padding=5)
        style.map("Modern.TEntry",
                  bordercolor=[("focus", THEME["accent"])])

        # Notebook / separators
        style.configure("TSeparator", background=THEME["border"])

    # ===== UI construction =================================================

    # Minimum body height: when the window is shorter than this, the
    # scrollbar appears so all controls remain reachable.
    MIN_BODY_HEIGHT = 720

    def _build_ui(self):
        # Header bar (always pinned to the top, not scrollable)
        header = ttk.Frame(self.root, style="App.TFrame")
        header.pack(fill="x", padx=22, pady=(18, 6))
        ttk.Label(header, text="CubeCtrl Visual Client", style="Title.TLabel"
                  ).pack(side="left")
        ttk.Label(header,
                  text="  PH585 · Closed-loop hardware-driven renderer",
                  style="Subtitle.TLabel").pack(side="left", padx=(8, 0), pady=(7, 0))

        # ── Scrollable body region ───────────────────────────────────────
        # Vertical scrollbar appears automatically when the window is
        # shorter than MIN_BODY_HEIGHT. When tall enough, the body fills
        # the viewport naturally and the scrollbar stays hidden.
        scroll_host = ttk.Frame(self.root, style="App.TFrame")
        scroll_host.pack(fill="both", expand=True)

        self._scroll_canvas = tk.Canvas(
            scroll_host, bg=THEME["bg"],
            highlightthickness=0, borderwidth=0, takefocus=0,
        )
        self._scroll_canvas.pack(side="left", fill="both", expand=True)

        self._scrollbar = ttk.Scrollbar(
            scroll_host, orient="vertical",
            command=self._scroll_canvas.yview,
        )
        # NOT packed initially -- _on_scroll_update will show/hide it.
        self._scrollbar_visible = False
        self._scroll_canvas.configure(yscrollcommand=self._on_scroll_update)

        # Inner frame holds the actual three-column body. It is positioned
        # inside the canvas via create_window so it becomes scrollable.
        inner = ttk.Frame(self._scroll_canvas, style="App.TFrame")
        self._scroll_inner = inner
        self._scroll_inner_window = self._scroll_canvas.create_window(
            (0, 0), window=inner, anchor="nw",
        )
        self._scroll_canvas.bind("<Configure>", self._on_canvas_configure)
        inner.bind("<Configure>", self._on_inner_configure)

        # Mouse-wheel scrolling (only forwards when scrollbar is active)
        self.root.bind_all("<MouseWheel>",  self._on_mousewheel)      # Windows / Mac
        self.root.bind_all("<Button-4>",    self._on_mousewheel_x11)  # Linux up
        self.root.bind_all("<Button-5>",    self._on_mousewheel_x11)  # Linux down

        # Three-column body: left (controls), center (3D view), right (log)
        body = ttk.Frame(inner, style="App.TFrame")
        body.pack(fill="both", expand=True, padx=18, pady=(6, 14))

        body.columnconfigure(0, weight=0, minsize=360)
        body.columnconfigure(1, weight=1, minsize=420)
        body.columnconfigure(2, weight=0, minsize=380)
        body.rowconfigure(0, weight=1)

        left_col = ttk.Frame(body, style="App.TFrame")
        mid_col  = ttk.Frame(body, style="App.TFrame")
        right_col = ttk.Frame(body, style="App.TFrame")
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        mid_col.grid(row=0, column=1, sticky="nsew", padx=8)
        right_col.grid(row=0, column=2, sticky="nsew", padx=(8, 0))

        self._build_connection_panel(left_col)
        self._build_controls_panel(left_col)
        self._build_render_panel(mid_col)
        self._build_log_panel(right_col)

        self._set_controls_enabled(False)

    # ---- Scroll wiring ----------------------------------------------------

    def _on_canvas_configure(self, event):
        """Resize the inner frame to match canvas width, with min-height floor."""
        w = event.width
        h = event.height
        inner_h = max(h, self.MIN_BODY_HEIGHT)
        self._scroll_canvas.itemconfigure(
            self._scroll_inner_window, width=w, height=inner_h)

    def _on_inner_configure(self, _event):
        """Inner frame changed natural size -> refresh scrollregion."""
        bbox = self._scroll_canvas.bbox("all")
        if bbox is not None:
            self._scroll_canvas.configure(scrollregion=bbox)

    def _on_scroll_update(self, lo, hi):
        """yscrollcommand: show/hide scrollbar automatically."""
        lo, hi = float(lo), float(hi)
        needs_bar = not (lo <= 0.0 and hi >= 1.0)
        if needs_bar and not self._scrollbar_visible:
            self._scrollbar.pack(side="right", fill="y")
            self._scrollbar_visible = True
        elif not needs_bar and self._scrollbar_visible:
            self._scrollbar.pack_forget()
            self._scrollbar_visible = False
        self._scrollbar.set(lo, hi)

    def _on_mousewheel(self, event):
        """Windows/Mac mouse wheel -> scroll canvas if scrollbar is active."""
        if not self._scrollbar_visible:
            return
        # event.delta: Windows = ±120 per notch, Mac = small ints
        if abs(event.delta) >= 120:
            steps = -int(event.delta / 120)
        else:
            steps = -int(event.delta) or (-1 if event.delta > 0 else 1)
        self._scroll_canvas.yview_scroll(steps, "units")

    def _on_mousewheel_x11(self, event):
        """Linux mouse wheel = Button-4/5 events."""
        if not self._scrollbar_visible:
            return
        steps = -1 if event.num == 4 else 1
        self._scroll_canvas.yview_scroll(steps, "units")

    # ---- Panel: Connection ------------------------------------------------

    def _build_connection_panel(self, parent):
        panel = self._card(parent, "Connection")
        panel.pack(fill="x", pady=(0, 10))

        inner = ttk.Frame(panel, style="Panel.TFrame")
        inner.pack(fill="x", padx=16, pady=(0, 14))

        ttk.Label(inner, text="Port",     style="PanelDim.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 2))
        ttk.Label(inner, text="Baud",     style="PanelDim.TLabel").grid(row=0, column=1, sticky="w", padx=(10, 0), pady=(0, 2))

        self.port_var = tk.StringVar(value=DEFAULT_PORT)
        self.port_combo = ttk.Combobox(inner, textvariable=self.port_var,
                                       width=11, style="Modern.TCombobox",
                                       font=("Segoe UI", 10))
        self.port_combo.grid(row=1, column=0, sticky="we", pady=(0, 10))

        self.baud_var = tk.StringVar(value="")
        self.baud_combo = ttk.Combobox(inner, textvariable=self.baud_var,
                                       values=[str(b) for b in BAUD_RATES],
                                       width=10, style="Modern.TCombobox",
                                       font=("Segoe UI", 10))
        self.baud_combo.grid(row=1, column=1, sticky="we", padx=(10, 0), pady=(0, 10))

        btn_row = ttk.Frame(inner, style="Panel.TFrame")
        btn_row.grid(row=2, column=0, columnspan=2, sticky="we", pady=(0, 4))
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)
        btn_row.columnconfigure(2, weight=1)

        self.refresh_btn = ttk.Button(btn_row, text="↻ Refresh",
                                      command=self._refresh_ports,
                                      style="Secondary.TButton")
        self.refresh_btn.grid(row=0, column=0, sticky="we", padx=(0, 4))

        self.detect_btn = ttk.Button(btn_row, text="Auto-Detect",
                                     command=self.on_detect,
                                     style="Secondary.TButton")
        self.detect_btn.grid(row=0, column=1, sticky="we", padx=4)

        self.connect_btn = ttk.Button(btn_row, text="Connect",
                                      command=self.on_connect,
                                      style="Primary.TButton")
        self.connect_btn.grid(row=0, column=2, sticky="we", padx=(4, 0))

        # Status line
        status_frame = ttk.Frame(panel, style="Panel.TFrame")
        status_frame.pack(fill="x", padx=16, pady=(0, 14))
        self._status_dot = tk.Canvas(status_frame, width=12, height=12,
                                     bg=THEME["panel"], highlightthickness=0)
        self._status_dot.pack(side="left", padx=(0, 8), pady=2)
        self._status_dot_id = self._status_dot.create_oval(
            1, 1, 11, 11, fill=THEME["danger"], outline="")
        self.status_var = tk.StringVar(value="Disconnected")
        self.status_lbl = ttk.Label(status_frame, textvariable=self.status_var,
                                    style="Status.TLabel")
        self.status_lbl.pack(side="left")

        # Disconnect (full-width, secondary)
        self.disconnect_btn = ttk.Button(panel, text="Disconnect",
                                         command=self.on_disconnect,
                                         style="Secondary.TButton",
                                         state="disabled")
        self.disconnect_btn.pack(fill="x", padx=16, pady=(0, 16))

    # ---- Panel: Controls (sliders + dice) ---------------------------------

    def _build_controls_panel(self, parent):
        panel = self._card(parent, "Controls")
        panel.pack(fill="both", expand=True)

        inner = ttk.Frame(panel, style="Panel.TFrame")
        inner.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # (code, label, lo, hi, default, sends_to_box)
        slider_specs = [
            ("HRYZ", "H-Rotation",   0, 359, DEFAULTS["HRYZ"], True),
            ("VERT", "V-Rotation",   0, 359, DEFAULTS["VERT"], True),
            ("COLR", "Color",        0, 359, DEFAULTS["COLR"], True),
            ("ZOOM", "Zoom",        50, 300, DEFAULTS["ZOOM"], True),
            ("BRT",  "Brightness",  20, 200, DEFAULTS["BRT"],  False),
        ]
        for code, lbl, lo, hi, default, sends in slider_specs:
            self._make_slider_row(inner, code, lbl, lo, hi, default, sends)
            ttk.Frame(inner, style="Panel.TFrame", height=6).pack(fill="x")

        # Dice dropdown
        ttk.Separator(inner, orient="horizontal").pack(fill="x", pady=(8, 12))

        dice_row = ttk.Frame(inner, style="Panel.TFrame")
        dice_row.pack(fill="x")
        ttk.Label(dice_row, text="Dice", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(dice_row,
                  text="Polyhedron shape sent as SET_SHPE",
                  style="PanelMute.TLabel").pack(anchor="w", pady=(0, 6))

        self.shape_var = tk.StringVar(value=DICE_PROTO_TO_DISPLAY[DEFAULTS["SHPE"]])
        self.shape_combo = ttk.Combobox(dice_row, textvariable=self.shape_var,
                                        values=DICE_DISPLAY, state="readonly",
                                        style="Modern.TCombobox",
                                        font=("Segoe UI", 10))
        self.shape_combo.pack(fill="x")
        self.shape_combo.bind("<<ComboboxSelected>>", self._on_shape_pick)

        # Raw command entry
        ttk.Separator(inner, orient="horizontal").pack(fill="x", pady=(14, 10))
        raw_lbl = ttk.Frame(inner, style="Panel.TFrame")
        raw_lbl.pack(fill="x")
        ttk.Label(raw_lbl, text="Raw Command", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(raw_lbl,
                  text="e.g.  SET_HRYZ:180   or   CUBECTRL:DISCONNECT",
                  style="PanelMute.TLabel").pack(anchor="w", pady=(0, 6))

        raw_row = ttk.Frame(inner, style="Panel.TFrame")
        raw_row.pack(fill="x")
        self.raw_var = tk.StringVar()
        self.raw_entry = ttk.Entry(raw_row, textvariable=self.raw_var,
                                   style="Modern.TEntry", font=("Consolas", 10))
        self.raw_entry.pack(side="left", fill="x", expand=True)
        self.raw_entry.bind("<Return>", lambda e: self._send_raw())
        ttk.Button(raw_row, text="Send", command=self._send_raw,
                   style="Primary.TButton").pack(side="left", padx=(8, 0))

    def _make_slider_row(self, parent, code, label, lo, hi, default, sends_to_box):
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill="x", pady=(4, 0))

        # Top line: label  ............  value
        top = ttk.Frame(row, style="Panel.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text=label, style="Heading.TLabel").pack(side="left")
        val_lbl = ttk.Label(top, text=str(default), style="Value.TLabel", width=4, anchor="e")
        val_lbl.pack(side="right")
        ttk.Label(top, text=f"  ({lo} – {hi})", style="PanelMute.TLabel"
                  ).pack(side="right")
        self.value_labels[code] = val_lbl

        def on_change(v, c=code, lab=val_lbl):
            lab.config(text=str(v))
            # Brightness is local-only: confirmed state updates immediately,
            # so the renderer reflects it without a roundtrip.
            if c == "BRT":
                self.confirmed["BRT"] = v

        def on_release(v, c=code, sends=sends_to_box):
            if sends:
                self._send_set(c, v)

        slider = ModernSlider(row, lo=lo, hi=hi, default=default,
                              on_change=on_change, on_release=on_release,
                              width=320, height=26)
        slider.pack(fill="x", pady=(4, 0))
        self.sliders[code] = slider

    def _on_shape_pick(self, _e):
        display = self.shape_var.get()
        proto = DICE_DISPLAY_TO_PROTO.get(display)
        if proto:
            self._send_cmd(f"SET_SHPE:{proto}")

    # ---- Panel: 3D viewport -----------------------------------------------

    def _build_render_panel(self, parent):
        panel = self._card(parent, "3D View")
        panel.pack(fill="both", expand=True)

        # Subtitle / placeholder text (visible when nothing has been confirmed yet)
        self.render_subtitle_var = tk.StringVar(
            value="Connect to the box to see the rendered shape.")
        ttk.Label(panel, textvariable=self.render_subtitle_var,
                  style="PanelMute.TLabel").pack(anchor="w", padx=16, pady=(0, 8))

        gl_holder = tk.Frame(panel, bg=THEME["render_bg"],
                             highlightthickness=1,
                             highlightbackground=THEME["border"])
        gl_holder.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._gl_holder = gl_holder

        if HAS_OPENGL:
            self.render_frame = RenderFrame(gl_holder, self.confirmed,
                                            width=400, height=400)
            self.render_frame.pack(fill="both", expand=True)
            self.render_frame.animate = 33  # ~30 fps
        else:
            self.render_frame = None
            placeholder = tk.Label(
                gl_holder,
                text=("3D View unavailable\n\n"
                      "Install with:\n"
                      "pip install PyOpenGL pyopengltk\n\n"
                      f"({_OPENGL_ERR})"),
                bg=THEME["render_bg"], fg=THEME["text_mute"],
                font=("Segoe UI", 10), justify="center")
            placeholder.pack(fill="both", expand=True)

    # ---- Panel: Log -------------------------------------------------------

    def _build_log_panel(self, parent):
        panel = self._card(parent, "Traffic Log")
        panel.pack(fill="both", expand=True)

        # ScrolledText is harder to style across platforms; use raw tk.Text
        text_holder = tk.Frame(panel, bg=THEME["panel"])
        text_holder.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        self.log_text = tk.Text(
            text_holder,
            bg=THEME["panel_lt"], fg=THEME["text"],
            insertbackground=THEME["text"],
            selectbackground=THEME["accent"], selectforeground="#ffffff",
            font=("Consolas", 9), wrap="none",
            borderwidth=0, highlightthickness=1,
            highlightbackground=THEME["border"],
            highlightcolor=THEME["border"],
            padx=8, pady=6,
        )
        scroll = ttk.Scrollbar(text_holder, command=self.log_text.yview)
        self.log_text.config(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

        self.log_text.tag_config("tx",  foreground=THEME["tx"])
        self.log_text.tag_config("rx",  foreground=THEME["rx"])
        self.log_text.tag_config("sys", foreground=THEME["sys"])
        self.log_text.tag_config("err", foreground=THEME["err"])

        btn_row = ttk.Frame(panel, style="Panel.TFrame")
        btn_row.pack(fill="x", padx=16, pady=(0, 14))
        ttk.Button(btn_row, text="Clear", command=self._clear_log,
                   style="Secondary.TButton").pack(side="left")
        ttk.Button(btn_row, text="Save Log…", command=self._save_log,
                   style="Secondary.TButton").pack(side="left", padx=8)

    # ---- Card helper ------------------------------------------------------

    def _card(self, parent, title):
        """A titled rounded-looking panel."""
        card = tk.Frame(parent, bg=THEME["panel"],
                        highlightthickness=1,
                        highlightbackground=THEME["border"])
        ttk.Label(card, text=title, style="Heading.TLabel"
                  ).pack(anchor="w", padx=16, pady=(14, 8))
        return card

    # ===== Command sending =================================================

    def _send_set(self, code, value):
        # All numeric values are zero-padded to 3 digits.
        self._send_cmd(f"SET_{code}:{int(value):03d}")

    def _send_raw(self):
        text = self.raw_var.get().strip()
        if text:
            self._send_cmd(text)
            self.raw_var.set("")

    def _send_cmd(self, cmd):
        if not self.ser or not self.ser.is_open:
            self._log("Not connected. Connect first.", "err")
            return
        try:
            self.ser.write((cmd + "\r\n").encode("ascii"))
            self.pending[cmd.split(":", 1)[0]] = time.time()
            self._log(f"PC →BOX  {label_for(cmd):<12} | {cmd}", "tx")
        except serial.SerialException as e:
            self._log(f"Send error: {e}", "err")

    # ===== Closed-loop state update ========================================
    #
    # confirmed state is ONLY mutated here (in response to incoming DRW_).
    # Brightness is the one exception -- it has no SET_/DRW_ pair, so its
    # slider's on_change updates self.confirmed["BRT"] directly.

    def _apply_drw(self, line):
        """Update confirmed state from a DRW_* echo line."""
        try:
            prefix, value = line.split(":", 1)
        except ValueError:
            return
        code = prefix[4:]  # strip "DRW_"
        if code == "SHPE":
            if value in SHAPE_BUILDERS:
                self.confirmed["shape"] = value
                # Update dropdown if the box reports a shape we didn't pick
                display = DICE_PROTO_TO_DISPLAY.get(value)
                if display and self.shape_var.get() != display:
                    self.shape_var.set(display)
            return
        if code in ("HRYZ", "VERT", "COLR", "ZOOM"):
            try:
                v = int(value)
            except ValueError:
                return
            self.confirmed[code] = v
            # If the slider has drifted from the confirmed value (e.g. on
            # initial-defaults sync), pull it into agreement WITHOUT firing
            # another SET_ send.
            sl = self.sliders.get(code)
            if sl and sl.get_value() != v:
                sl.set_value(v, fire_callbacks=False)
                vl = self.value_labels.get(code)
                if vl:
                    vl.config(text=str(v))

    # ===== Connection lifecycle ===========================================

    def _refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if not ports:
            ports = [DEFAULT_PORT]
        self.port_combo["values"] = ports
        if self.port_var.get() not in ports:
            self.port_var.set(ports[0])

    def on_detect(self):
        port = self.port_var.get().strip()
        if not port:
            messagebox.showerror("No port", "Please specify a COM port.")
            return
        self.detect_btn.config(state="disabled")
        self.connect_btn.config(state="disabled")
        self.detect_stop.clear()
        self._log(f"Starting baud auto-detection on {port} …", "sys")
        self._set_status("Detecting baud…", THEME["warn"])

        def worker():
            baud = detect_baud(
                port,
                status_cb=lambda m: self.gui_queue.put(("log", m, "sys")),
                stop_event=self.detect_stop,
            )
            self.gui_queue.put(("detect_done", baud, None))

        self.detect_thread = threading.Thread(target=worker, daemon=True)
        self.detect_thread.start()

    def on_connect(self):
        port = self.port_var.get().strip()
        baud_str = self.baud_var.get().strip()
        if not baud_str.isdigit():
            messagebox.showerror("Baud required",
                                 "Pick a baud rate (or click Auto-Detect first).")
            return
        baud = int(baud_str)

        try:
            self.ser = serial.Serial(port, baud, timeout=0.1, **FRAME_FORMAT)
        except serial.SerialException as e:
            messagebox.showerror("Connection failed", str(e))
            self.ser = None
            return

        self._log(f"Connected to {port} at {baud} baud (8N1).", "sys")
        self._set_status(f"Connected · {port} @ {baud}", THEME["success"])

        # Reset confirmed state -- the renderer stays blank until the box
        # echoes back its acknowledgements.
        self.confirmed["shape"] = None
        for k in ("HRYZ", "VERT", "COLR", "ZOOM"):
            self.confirmed[k] = 0
        self.render_subtitle_var.set(
            "Sending defaults… waiting for DRW_ echoes from box.")

        self.reader_stop.clear()
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()

        self.connect_btn.config(state="disabled")
        self.disconnect_btn.config(state="normal")
        self.detect_btn.config(state="disabled")
        self.refresh_btn.config(state="disabled")
        self._set_controls_enabled(True)

        # Handshake (best-effort -- box may ignore it)
        self._send_cmd("CUBECTRL:CONNECT")

        # Push all defaults so the box draws the initial state. The renderer
        # only updates as DRW_ echoes arrive.
        self.root.after(60,  lambda: self._send_set("HRYZ", DEFAULTS["HRYZ"]))
        self.root.after(120, lambda: self._send_set("VERT", DEFAULTS["VERT"]))
        self.root.after(180, lambda: self._send_set("COLR", DEFAULTS["COLR"]))
        self.root.after(240, lambda: self._send_set("ZOOM", DEFAULTS["ZOOM"]))
        self.root.after(300, lambda: self._send_cmd(f"SET_SHPE:{DEFAULTS['SHPE']}"))

    def on_disconnect(self):
        # Polite goodbye -- matches PortSniffLab behavior.
        if self.ser is not None and self.ser.is_open:
            try:
                self.ser.write(b"CUBECTRL:DISCONNECT\r\n")
                self._log(f"PC →BOX  {'Handshake':<12} | CUBECTRL:DISCONNECT", "tx")
                time.sleep(0.1)
            except serial.SerialException:
                pass

        self.reader_stop.set()
        if self.reader_thread is not None:
            self.reader_thread.join(timeout=1.0)
            self.reader_thread = None
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

        # Blank the renderer -- no confirmed state means nothing to draw.
        self.confirmed["shape"] = None
        self.render_subtitle_var.set(
            "Connect to the box to see the rendered shape.")

        self._log("Disconnected.", "sys")
        self._set_status("Disconnected", THEME["danger"])
        self.connect_btn.config(state="normal")
        self.disconnect_btn.config(state="disabled")
        self.detect_btn.config(state="normal")
        self.refresh_btn.config(state="normal")
        self._set_controls_enabled(False)

    # ===== Reader thread ===================================================

    def _reader_loop(self):
        buf = ""
        while not self.reader_stop.is_set() and self.ser and self.ser.is_open:
            try:
                data = self.ser.read(self.ser.in_waiting or 1)
                if data:
                    buf += data.decode("ascii", errors="replace")
                    while "\n" in buf:
                        raw, buf = buf.split("\n", 1)
                        line = clean_line(raw)
                        if line:
                            self.gui_queue.put(("rx", line, None))
            except serial.SerialException as e:
                self.gui_queue.put(("log", f"Reader error: {e}", "err"))
                break
            except Exception as e:
                self.gui_queue.put(("log", f"Reader exception: {e}", "err"))
                break

    # ===== Queue pump =====================================================

    def _poll_queue(self):
        try:
            while True:
                kind, payload, extra = self.gui_queue.get_nowait()
                if kind == "rx":
                    line = payload
                    self._log(f"BOX→PC   {label_for(line):<12} | {line}", "rx")
                    # CLOSED LOOP: this is the only place confirmed state changes
                    if line.startswith("DRW_"):
                        was_blank = self.confirmed["shape"] is None
                        self._apply_drw(line)
                        if was_blank and self.confirmed["shape"] is not None:
                            self.render_subtitle_var.set(
                                "Live render reflects last confirmed state from box.")
                elif kind == "log":
                    self._log(payload, extra or "sys")
                elif kind == "detect_done":
                    baud = payload
                    self.detect_btn.config(state="normal")
                    self.connect_btn.config(state="normal")
                    if baud:
                        self.baud_var.set(str(baud))
                        self._log(f"==> Baud detected: {baud}. Click Connect.", "sys")
                        self._set_status(f"Baud {baud} detected", THEME["success"])
                    else:
                        self._log("Baud detection failed.", "err")
                        self._set_status("Detection failed", THEME["danger"])
        except queue.Empty:
            pass
        self.root.after(40, self._poll_queue)

    # ===== Helpers =========================================================

    def _log(self, msg, tag="sys"):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_text.insert("end", f"[{ts}] {msg}\n", tag)
        self.log_text.see("end")

    def _clear_log(self):
        self.log_text.delete("1.0", "end")

    def _save_log(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".log",
            filetypes=[("Log files", "*.log"), ("Text", "*.txt"), ("All", "*.*")],
            initialfile="cubectrl_capture.log",
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_text.get("1.0", "end"))
            self._log(f"Log saved to {path}", "sys")

    def _set_status(self, text, color):
        self.status_var.set(text)
        self.status_lbl.configure(foreground=color)
        self._status_dot.itemconfigure(self._status_dot_id, fill=color)

    def _set_controls_enabled(self, enabled):
        # All hardware sliders + dice + raw entry require a connection.
        # Brightness slider stays enabled always (local-only).
        for code, sl in self.sliders.items():
            if code == "BRT":
                sl.set_enabled(True)
            else:
                sl.set_enabled(enabled)
        self.shape_combo.config(state=("readonly" if enabled else "disabled"))
        self.raw_entry.config(state=("normal" if enabled else "disabled"))

    def on_close(self):
        try:
            self.detect_stop.set()
            if self.ser is not None:
                self.on_disconnect()
            if HAS_OPENGL and self.render_frame is not None:
                try:
                    self.render_frame.animate = 0
                except Exception:
                    pass
        finally:
            self.root.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()
    app = CubeCtrlApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()