"""
UV Photolithography Mask Generator (v2)
=======================================
Editor for binary masks on subpixel-addressed monochrome LCDs.

The panel has 8520 physical column drivers, but the MIPI-to-HDMI bridge
accepts a 2840-wide input frame. Each input pixel's R, G, B channels each
drive a separate physical column on the panel. With color filters removed
(or absent), every subpixel just transmits UV equally.

Two drawing modes (toggle in the toolbar):
    REGION         - design a small pattern (e.g. 200x100) and position it
                     on the LCD via the offset fields.
    FULL CANVAS    - draw directly on the full 8520x4320 grid. Use mouse
                     wheel to zoom (Ctrl+wheel), middle-button drag to pan,
                     Goto to jump to coordinates.

On save the script emits a 2840x4320 RGB PNG where:
    R channel  -> physical columns 0, 3, 6, ...
    G channel  -> physical columns 1, 4, 7, ...
    B channel  -> physical columns 2, 5, 8, ...
If your panel's subpixel order is BGR (B leftmost), set SUBPIXEL_ORDER below.

Requires: numpy, Pillow.   Install:  pip install numpy pillow
"""

import json
import os
import zlib
import tkinter as tk
from tkinter import filedialog, messagebox

import numpy as np
from PIL import Image, ImageTk


# ----- Panel configuration -----
LCD_WIDTH      = 8520
LCD_HEIGHT     = 4320
H_COMPRESSION  = 3
OUTPUT_WIDTH   = LCD_WIDTH // H_COMPRESSION    # 2840
OUTPUT_HEIGHT  = LCD_HEIGHT                    # 4320
SUBPIXEL_ORDER = "RGB"   # "RGB" (R leftmost) or "BGR" (B leftmost)
# -------------------------------


class MaskGenerator:
    def __init__(self, root):
        self.root = root
        self.root.title("UV Lithography Mask Generator v2")
        self.root.geometry("1200x820")

        self.design_w = 240
        self.design_h = 120
        self.pattern = np.zeros((self.design_h, self.design_w), dtype=np.uint8)
        self.pixel_size = 6.0

        # Tk vars
        self.w_var = tk.IntVar(value=self.design_w)
        self.h_var = tk.IntVar(value=self.design_h)
        self.ox_var = tk.IntVar(value=(LCD_WIDTH - self.design_w) // 2)
        self.oy_var = tk.IntVar(value=(LCD_HEIGHT - self.design_h) // 2)
        self.brush_var = tk.IntVar(value=1)
        self.subpixel_mode = tk.BooleanVar(value=True)
        self.invert_output = tk.BooleanVar(value=False)
        self.show_grid = tk.BooleanVar(value=True)
        self.full_canvas_mode = tk.BooleanVar(value=False)

        # Compressed undo history (so 8520x4320 doesn't eat all your RAM)
        self.history = []
        self.history_idx = -1
        self.MAX_HISTORY = 50

        self.mouse_down = False
        self._dirty_after = None

        self._build_ui()
        self._save_history()
        self.root.after(50, self._render)

    # ------------------------------------------------------------------
    def _build_ui(self):
        bar = tk.Frame(self.root, padx=6, pady=4)
        bar.pack(side=tk.TOP, fill=tk.X)

        tk.Label(bar, text="Design (LCD px):").pack(side=tk.LEFT)
        self.spin_w = tk.Spinbox(bar, from_=8, to=LCD_WIDTH, width=6, textvariable=self.w_var)
        self.spin_w.pack(side=tk.LEFT)
        tk.Label(bar, text=" x ").pack(side=tk.LEFT)
        self.spin_h = tk.Spinbox(bar, from_=8, to=LCD_HEIGHT, width=6, textvariable=self.h_var)
        self.spin_h.pack(side=tk.LEFT)
        self.btn_resize = tk.Button(bar, text="Resize", command=self._resize)
        self.btn_resize.pack(side=tk.LEFT, padx=4)

        tk.Label(bar, text="   Brush:").pack(side=tk.LEFT)
        tk.Spinbox(bar, from_=1, to=50, width=3, textvariable=self.brush_var).pack(side=tk.LEFT)

        tk.Checkbutton(bar, text="Subpixel encode (3x H)", variable=self.subpixel_mode).pack(side=tk.LEFT, padx=10)
        tk.Checkbutton(bar, text="Invert", variable=self.invert_output).pack(side=tk.LEFT)
        tk.Checkbutton(bar, text="Grid", variable=self.show_grid, command=self._render).pack(side=tk.LEFT)

        # Highlighted toggle for full canvas mode
        self.btn_fullcanvas = tk.Checkbutton(
            bar, text="FULL LCD CANVAS  8520 x 4320",
            variable=self.full_canvas_mode,
            command=self._toggle_full_canvas,
            bg="#333", fg="white", selectcolor="#2a6a6a",
            activebackground="#444", activeforeground="white",
            indicatoron=False, padx=10, pady=3, font=("TkDefaultFont", 9, "bold"))
        self.btn_fullcanvas.pack(side=tk.RIGHT, padx=8)

        bar2 = tk.Frame(self.root, padx=6, pady=4)
        bar2.pack(side=tk.TOP, fill=tk.X)

        tk.Label(bar2, text="LCD offset (px):").pack(side=tk.LEFT)
        self.spin_ox = tk.Spinbox(bar2, from_=0, to=LCD_WIDTH, width=6, textvariable=self.ox_var)
        self.spin_ox.pack(side=tk.LEFT)
        self.spin_oy = tk.Spinbox(bar2, from_=0, to=LCD_HEIGHT, width=6, textvariable=self.oy_var)
        self.spin_oy.pack(side=tk.LEFT)
        self.btn_center = tk.Button(bar2, text="Center", command=self._center)
        self.btn_center.pack(side=tk.LEFT, padx=4)

        tk.Button(bar2, text="Zoom +",  command=lambda: self._zoom(1.25)).pack(side=tk.LEFT, padx=2)
        tk.Button(bar2, text="Zoom -",  command=lambda: self._zoom(0.8)).pack(side=tk.LEFT, padx=2)
        tk.Button(bar2, text="Fit",     command=self._fit).pack(side=tk.LEFT, padx=2)
        tk.Button(bar2, text="1:1",     command=lambda: self._set_zoom(1.0)).pack(side=tk.LEFT, padx=2)
        tk.Button(bar2, text="Goto...", command=self._goto_dialog).pack(side=tk.LEFT, padx=4)

        tk.Button(bar2, text="Clear", command=self._clear).pack(side=tk.LEFT, padx=8)
        tk.Button(bar2, text="Undo",  command=self._undo).pack(side=tk.LEFT)
        tk.Button(bar2, text="Redo",  command=self._redo).pack(side=tk.LEFT)

        tk.Button(bar2, text="Save Mask PNG", command=self._save_png,
                  bg="#3a7a3a", fg="white", padx=8).pack(side=tk.RIGHT, padx=3)
        tk.Button(bar2, text="Save Project",  command=self._save_project).pack(side=tk.RIGHT, padx=2)
        tk.Button(bar2, text="Load Project",  command=self._load_project).pack(side=tk.RIGHT, padx=2)
        tk.Button(bar2, text="Test Patterns", command=self._test_pattern_menu).pack(side=tk.RIGHT, padx=2)

        # Canvas
        frame = tk.Frame(self.root)
        frame.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(frame, bg="#1a1a1a", highlightthickness=0)
        self.hbar = tk.Scrollbar(frame, orient=tk.HORIZONTAL)
        self.vbar = tk.Scrollbar(frame, orient=tk.VERTICAL)
        self.canvas.configure(xscrollcommand=self._x_set, yscrollcommand=self._y_set)
        self.hbar.config(command=self.canvas.xview)
        self.vbar.config(command=self.canvas.yview)
        self.vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.hbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Bindings
        self.canvas.bind("<Button-1>",        lambda e: self._press(e, 1))
        self.canvas.bind("<Button-3>",        lambda e: self._press(e, 0))
        self.canvas.bind("<B1-Motion>",       lambda e: self._drag(e, 1))
        self.canvas.bind("<B3-Motion>",       lambda e: self._drag(e, 0))
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<ButtonRelease-3>", self._release)
        self.canvas.bind("<Motion>",          self._status)
        self.canvas.bind("<Configure>",       lambda e: self._request_render())
        # Middle-button pan
        self.canvas.bind("<Button-2>",        self._pan_start)
        self.canvas.bind("<B2-Motion>",       self._pan_move)
        # Mousewheel: scroll, Ctrl+wheel zoom, Shift+wheel horizontal
        self.canvas.bind("<MouseWheel>",         self._on_mousewheel)
        self.canvas.bind("<Control-MouseWheel>", self._on_ctrl_mousewheel)
        self.canvas.bind("<Shift-MouseWheel>",   self._on_shift_mousewheel)
        # Linux
        self.canvas.bind("<Button-4>", lambda e: self._mousewheel_linux(e, 1))
        self.canvas.bind("<Button-5>", lambda e: self._mousewheel_linux(e, -1))

        self.status = tk.Label(self.root, text="Ready", anchor=tk.W,
                               relief=tk.SUNKEN, padx=5)
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

        self.root.bind("<Control-z>", lambda e: self._undo())
        self.root.bind("<Control-y>", lambda e: self._redo())
        self.root.bind("<Control-s>", lambda e: self._save_png())
        self.root.bind("<plus>",  lambda e: self._zoom(1.25))
        self.root.bind("<equal>", lambda e: self._zoom(1.25))
        self.root.bind("<minus>", lambda e: self._zoom(0.8))

    # ---------- Mode toggle ----------
    def _toggle_full_canvas(self):
        if self.full_canvas_mode.get():
            # Expand to full 8520x4320 with current pattern placed at offset
            full = np.zeros((LCD_HEIGHT, LCD_WIDTH), dtype=np.uint8)
            ox, oy = self.ox_var.get(), self.oy_var.get()
            h, w = self.pattern.shape
            x0 = max(0, ox); y0 = max(0, oy)
            x1 = min(LCD_WIDTH, ox + w); y1 = min(LCD_HEIGHT, oy + h)
            if x1 > x0 and y1 > y0:
                full[y0:y1, x0:x1] = self.pattern[y0-oy:y0-oy+(y1-y0),
                                                  x0-ox:x0-ox+(x1-x0)]
            self.pattern = full
            self.design_w, self.design_h = LCD_WIDTH, LCD_HEIGHT
            self.w_var.set(LCD_WIDTH); self.h_var.set(LCD_HEIGHT)
            self.ox_var.set(0); self.oy_var.set(0)
            for w in (self.spin_w, self.spin_h, self.btn_resize,
                      self.spin_ox, self.spin_oy, self.btn_center):
                w.config(state=tk.DISABLED)
            self._save_history()
            self._fit()
        else:
            if not messagebox.askyesno(
                "Switch to Region",
                "Switching back to Region mode will crop to 240x120 from (0,0).\n"
                "Continue?\n\n"
                "(To save your full-canvas work first, click No, then Save Project.)"):
                self.full_canvas_mode.set(True)
                return
            self.pattern = self.pattern[:120, :240].copy()
            self.design_w, self.design_h = 240, 120
            self.w_var.set(240); self.h_var.set(120)
            for w in (self.spin_w, self.spin_h, self.btn_resize,
                      self.spin_ox, self.spin_oy, self.btn_center):
                w.config(state=tk.NORMAL)
            self._save_history()
            self._fit()

    # ---------- Viewport-aware rendering ----------
    def _render(self):
        if self._dirty_after is not None:
            try: self.root.after_cancel(self._dirty_after)
            except Exception: pass
            self._dirty_after = None

        self.canvas.delete("all")
        ps = self.pixel_size
        total_w = max(1, int(self.design_w * ps))
        total_h = max(1, int(self.design_h * ps))
        self.canvas.configure(scrollregion=(0, 0, total_w, total_h))

        cw = self.canvas.winfo_width(); ch = self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            self.root.after(50, self._render); return

        xv = self.canvas.xview(); yv = self.canvas.yview()
        vx0 = int(xv[0] * total_w); vy0 = int(yv[0] * total_h)
        vx1 = int(xv[1] * total_w) + 1; vy1 = int(yv[1] * total_h) + 1
        margin = max(1, int(ps * 8))
        vx0 = max(0, vx0 - margin); vy0 = max(0, vy0 - margin)
        vx1 = min(total_w, vx1 + margin); vy1 = min(total_h, vy1 + margin)

        px0 = max(0, int(vx0 / ps))
        py0 = max(0, int(vy0 / ps))
        px1 = min(self.design_w, int(vx1 / ps) + 1)
        py1 = min(self.design_h, int(vy1 / ps) + 1)
        if px1 <= px0 or py1 <= py0: return

        sub = self.pattern[py0:py1, px0:px1]
        out_w = max(1, int((px1 - px0) * ps))
        out_h = max(1, int((py1 - py0) * ps))
        img = Image.fromarray(sub * 255, mode='L').convert('RGB')
        img = img.resize((out_w, out_h), Image.NEAREST)
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.create_image(int(px0 * ps), int(py0 * ps),
                                 image=self._photo, anchor=tk.NW)

        if self.show_grid.get() and ps >= 4:
            x_start = int(px0 * ps); y_start = int(py0 * ps)
            x_end = int(px1 * ps); y_end = int(py1 * ps)
            for i in range(px0, px1 + 1):
                x = int(i * ps)
                self.canvas.create_line(x, y_start, x, y_end, fill="#3a3a3a")
            for i in range(py0, py1 + 1):
                y = int(i * ps)
                self.canvas.create_line(x_start, y, x_end, y, fill="#3a3a3a")

    def _request_render(self):
        if self._dirty_after is None:
            self._dirty_after = self.root.after(16, self._render)

    def _x_set(self, *args):
        self.hbar.set(*args); self._request_render()

    def _y_set(self, *args):
        self.vbar.set(*args); self._request_render()

    # ---------- Painting ----------
    def _evt_to_px(self, e):
        x = int(self.canvas.canvasx(e.x) / self.pixel_size)
        y = int(self.canvas.canvasy(e.y) / self.pixel_size)
        return x, y

    def _paint(self, x, y, val):
        b = self.brush_var.get(); r = b // 2
        x0 = max(0, x - r); y0 = max(0, y - r)
        x1 = min(self.design_w, x + r + 1); y1 = min(self.design_h, y + r + 1)
        if x1 > x0 and y1 > y0:
            self.pattern[y0:y1, x0:x1] = val
            return True
        return False

    def _press(self, e, val):
        self.mouse_down = True
        if self._paint(*self._evt_to_px(e), val):
            self._request_render()

    def _drag(self, e, val):
        if not self.mouse_down: return
        x, y = self._evt_to_px(e)
        if 0 <= x < self.design_w and 0 <= y < self.design_h:
            if self._paint(x, y, val):
                self._request_render()

    def _release(self, e):
        if self.mouse_down:
            self.mouse_down = False
            self._render()
            self._save_history()

    def _status(self, e):
        x, y = self._evt_to_px(e)
        if 0 <= x < self.design_w and 0 <= y < self.design_h:
            if self.full_canvas_mode.get():
                ox, oy = x, y
            else:
                ox = self.ox_var.get() + x; oy = self.oy_var.get() + y
            mode = "Full" if self.full_canvas_mode.get() else "Region"
            self.status.config(
                text=f"Pattern ({x},{y}) | LCD ({ox},{oy}) | "
                     f"{mode} {self.design_w}x{self.design_h} | "
                     f"Zoom {self.pixel_size:.3f}x | "
                     f"Out {OUTPUT_WIDTH}x{OUTPUT_HEIGHT} "
                     f"{'[subpixel]' if self.subpixel_mode.get() else '[plain]'}")

    # ---------- Pan and zoom ----------
    def _pan_start(self, e):
        self.canvas.scan_mark(e.x, e.y)

    def _pan_move(self, e):
        self.canvas.scan_dragto(e.x, e.y, gain=1)
        self._request_render()

    def _on_mousewheel(self, e):
        d = 1 if e.delta > 0 else -1
        self.canvas.yview_scroll(-d * 3, "units")

    def _on_ctrl_mousewheel(self, e):
        f = 1.25 if e.delta > 0 else 0.8
        self._zoom_at(e.x, e.y, f)

    def _on_shift_mousewheel(self, e):
        d = 1 if e.delta > 0 else -1
        self.canvas.xview_scroll(-d * 3, "units")

    def _mousewheel_linux(self, e, direction):
        if e.state & 0x4:
            f = 1.25 if direction > 0 else 0.8
            self._zoom_at(e.x, e.y, f)
        elif e.state & 0x1:
            self.canvas.xview_scroll(-direction * 3, "units")
        else:
            self.canvas.yview_scroll(-direction * 3, "units")

    def _zoom(self, factor):
        self._zoom_at(self.canvas.winfo_width() // 2,
                      self.canvas.winfo_height() // 2, factor)

    def _zoom_at(self, sx, sy, factor):
        cx = self.canvas.canvasx(sx); cy = self.canvas.canvasy(sy)
        px = cx / self.pixel_size; py = cy / self.pixel_size
        self.pixel_size = max(0.05, min(64.0, self.pixel_size * factor))
        total_w = max(1, int(self.design_w * self.pixel_size))
        total_h = max(1, int(self.design_h * self.pixel_size))
        self.canvas.configure(scrollregion=(0, 0, total_w, total_h))
        new_cx = px * self.pixel_size; new_cy = py * self.pixel_size
        self.canvas.xview_moveto(max(0, (new_cx - sx)) / total_w)
        self.canvas.yview_moveto(max(0, (new_cy - sy)) / total_h)
        self._render()

    def _set_zoom(self, val):
        self.pixel_size = val; self._render()

    def _fit(self):
        self.canvas.update_idletasks()
        cw = self.canvas.winfo_width(); ch = self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            self.root.after(50, self._fit); return
        self.pixel_size = max(0.05, min(cw / self.design_w, ch / self.design_h))
        self.canvas.xview_moveto(0); self.canvas.yview_moveto(0)
        self._render()

    def _goto_dialog(self):
        win = tk.Toplevel(self.root); win.title("Go to LCD coordinate")
        tk.Label(win, text="LCD X:").grid(row=0, column=0, padx=4, pady=4, sticky=tk.E)
        x_var = tk.IntVar(value=LCD_WIDTH // 2)
        tk.Entry(win, textvariable=x_var, width=10).grid(row=0, column=1, padx=4)
        tk.Label(win, text="LCD Y:").grid(row=1, column=0, padx=4, pady=4, sticky=tk.E)
        y_var = tk.IntVar(value=LCD_HEIGHT // 2)
        tk.Entry(win, textvariable=y_var, width=10).grid(row=1, column=1, padx=4)
        def go():
            x = x_var.get(); y = y_var.get()
            if self.full_canvas_mode.get():
                px, py = x, y
            else:
                px = x - self.ox_var.get(); py = y - self.oy_var.get()
            cx = px * self.pixel_size; cy = py * self.pixel_size
            total_w = max(1, self.design_w * self.pixel_size)
            total_h = max(1, self.design_h * self.pixel_size)
            cw = self.canvas.winfo_width(); ch = self.canvas.winfo_height()
            self.canvas.xview_moveto(max(0, (cx - cw/2)) / total_w)
            self.canvas.yview_moveto(max(0, (cy - ch/2)) / total_h)
            self._render(); win.destroy()
        tk.Button(win, text="Go", command=go, width=10).grid(row=2, column=0, columnspan=2, pady=6)
        win.bind("<Return>", lambda e: go())

    # ---------- Pattern ops ----------
    def _resize(self):
        nw = max(8, self.w_var.get()); nh = max(8, self.h_var.get())
        new = np.zeros((nh, nw), dtype=np.uint8)
        ch = min(nh, self.design_h); cw = min(nw, self.design_w)
        new[:ch, :cw] = self.pattern[:ch, :cw]
        self.pattern = new
        self.design_w, self.design_h = nw, nh
        self._save_history(); self._render()

    def _center(self):
        self.ox_var.set(max(0, (LCD_WIDTH - self.design_w) // 2))
        self.oy_var.set(max(0, (LCD_HEIGHT - self.design_h) // 2))

    def _clear(self):
        if messagebox.askyesno("Clear", "Clear the entire design?"):
            self.pattern[:] = 0
            self._save_history(); self._render()

    # ---------- Compressed undo ----------
    def _compress(self, arr):
        return (arr.shape, zlib.compress(arr.tobytes(), level=1))

    def _decompress(self, blob):
        shape, data = blob
        return np.frombuffer(zlib.decompress(data), dtype=np.uint8).reshape(shape).copy()

    def _save_history(self):
        if self.history_idx < len(self.history) - 1:
            self.history = self.history[:self.history_idx + 1]
        self.history.append(self._compress(self.pattern))
        if len(self.history) > self.MAX_HISTORY:
            self.history.pop(0)
        self.history_idx = len(self.history) - 1

    def _undo(self):
        if self.history_idx > 0:
            self.history_idx -= 1
            self.pattern = self._decompress(self.history[self.history_idx])
            self.design_h, self.design_w = self.pattern.shape
            self.w_var.set(self.design_w); self.h_var.set(self.design_h)
            self._render()

    def _redo(self):
        if self.history_idx < len(self.history) - 1:
            self.history_idx += 1
            self.pattern = self._decompress(self.history[self.history_idx])
            self.design_h, self.design_w = self.pattern.shape
            self.w_var.set(self.design_w); self.h_var.set(self.design_h)
            self._render()

    # ---------- Test patterns ----------
    def _test_pattern_menu(self):
        win = tk.Toplevel(self.root); win.title("Diagnostic patterns")
        tk.Label(win, text="Save full-frame test PNGs (2840x4320, HDMI-ready).",
                 padx=10, pady=6).pack()
        for name, fn in [
            ("Single column R / G / B (3 files)",      self._tp_single_columns),
            ("Solid R / G / B / Y / W (5 files)",      self._tp_solid_rgb),
            ("Subpixel resolution chart (1-10 px)",     self._tp_resolution_chart),
        ]:
            tk.Button(win, text=name, command=lambda f=fn: (f(), win.destroy()),
                      width=40, anchor=tk.W).pack(padx=10, pady=2)

    def _ask_dir(self):
        return filedialog.askdirectory(title="Save tests to folder")

    def _tp_single_columns(self):
        d = self._ask_dir()
        if not d: return
        for nm, idx in [("R", 0), ("G", 1), ("B", 2)]:
            arr = np.zeros((OUTPUT_HEIGHT, OUTPUT_WIDTH, 3), dtype=np.uint8)
            arr[:, OUTPUT_WIDTH // 2, idx] = 255
            Image.fromarray(arr).save(os.path.join(d, f"test_column_{nm}.png"))
        self.status.config(text=f"Single-column tests saved to {d}")

    def _tp_solid_rgb(self):
        d = self._ask_dir()
        if not d: return
        for nm, color in [("R", (255,0,0)), ("G", (0,255,0)),
                          ("B", (0,0,255)), ("Y", (255,255,0)),
                          ("W", (255,255,255))]:
            arr = np.full((OUTPUT_HEIGHT, OUTPUT_WIDTH, 3), color, dtype=np.uint8)
            Image.fromarray(arr).save(os.path.join(d, f"test_solid_{nm}.png"))
        self.status.config(text=f"Solid color tests saved to {d}")

    def _tp_resolution_chart(self):
        path = filedialog.asksaveasfilename(defaultextension=".png",
                                            filetypes=[("PNG", "*.png")],
                                            initialfile="resolution_chart.png")
        if not path: return
        full = np.zeros((LCD_HEIGHT, LCD_WIDTH), dtype=np.uint8)
        x = 50
        for pitch in range(1, 11):
            for _ in range(20):
                if x + pitch >= LCD_WIDTH - 50: break
                full[:, x:x + pitch] = 255
                x += pitch * 2
            x += 30
        self._encode_and_save(full, path)
        self.status.config(text=f"Resolution chart -> {os.path.basename(path)}")

    # ---------- Output ----------
    def _build_full(self):
        if self.full_canvas_mode.get():
            return self.pattern * 255
        full = np.zeros((LCD_HEIGHT, LCD_WIDTH), dtype=np.uint8)
        ox = self.ox_var.get(); oy = self.oy_var.get()
        h, w = self.pattern.shape
        x0 = max(0, ox); y0 = max(0, oy)
        x1 = min(LCD_WIDTH, ox + w); y1 = min(LCD_HEIGHT, oy + h)
        if x1 > x0 and y1 > y0:
            full[y0:y1, x0:x1] = self.pattern[y0-oy:y0-oy+(y1-y0),
                                              x0-ox:x0-ox+(x1-x0)] * 255
        return full

    def _encode_and_save(self, full, path):
        if self.invert_output.get():
            full = 255 - full
        if self.subpixel_mode.get():
            out = np.zeros((OUTPUT_HEIGHT, OUTPUT_WIDTH, 3), dtype=np.uint8)
            cols = [full[:, 0::3], full[:, 1::3], full[:, 2::3]]
            if SUBPIXEL_ORDER == "BGR":
                cols = cols[::-1]
            out[:, :, 0], out[:, :, 1], out[:, :, 2] = cols
            Image.fromarray(out, mode='RGB').save(path)
        else:
            packed = np.maximum.reduce([full[:, 0::3], full[:, 1::3], full[:, 2::3]])
            Image.fromarray(packed, mode='L').save(path)

    def _save_png(self):
        path = filedialog.asksaveasfilename(defaultextension=".png",
                                            filetypes=[("PNG", "*.png")],
                                            initialfile="mask.png")
        if not path: return
        self._encode_and_save(self._build_full(), path)
        mode = "subpixel-encoded RGB" if self.subpixel_mode.get() else "plain grayscale"
        self.status.config(text=f"Saved {OUTPUT_WIDTH}x{OUTPUT_HEIGHT} {mode} "
                                f"-> {os.path.basename(path)}")

    def _save_project(self):
        path = filedialog.asksaveasfilename(defaultextension=".npz",
                                            filetypes=[("Project", "*.npz")])
        if not path: return
        np.savez_compressed(path,
            pattern=self.pattern,
            offset=np.array([self.ox_var.get(), self.oy_var.get()]),
            options=np.array([int(self.subpixel_mode.get()),
                              int(self.invert_output.get()),
                              int(self.full_canvas_mode.get())]))
        self.status.config(text=f"Project saved: {os.path.basename(path)}")

    def _load_project(self):
        path = filedialog.askopenfilename(filetypes=[("Project", "*.npz")])
        if not path: return
        data = np.load(path)
        self.pattern = data["pattern"].astype(np.uint8)
        ox, oy = data["offset"].tolist()
        self.ox_var.set(int(ox)); self.oy_var.set(int(oy))
        opts = data["options"].tolist()
        self.subpixel_mode.set(bool(opts[0]))
        self.invert_output.set(bool(opts[1]))
        full_mode = bool(opts[2])
        self.full_canvas_mode.set(full_mode)
        self.design_h, self.design_w = self.pattern.shape
        self.w_var.set(self.design_w); self.h_var.set(self.design_h)
        for w in (self.spin_w, self.spin_h, self.btn_resize,
                  self.spin_ox, self.spin_oy, self.btn_center):
            w.config(state=(tk.DISABLED if full_mode else tk.NORMAL))
        self._save_history(); self._fit()


if __name__ == "__main__":
    root = tk.Tk()
    MaskGenerator(root)
    root.mainloop()