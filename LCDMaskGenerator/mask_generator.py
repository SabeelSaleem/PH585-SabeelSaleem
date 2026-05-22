"""
UV Photolithography Mask Generator (v3)
=======================================
For a monochrome LCD with 8520 physical columns driven by a 2840-wide
HDMI feed (each input pixel's R/G/B channels each drive a separate
physical column). Subpixel order: RGB (R leftmost).

Three modes:
  - TILE        : draw on one tile; output is replicated N×M to fill the
                  panel. N and M are independently selectable from the
                  factors of 8520 and 4320 so every tile is exact integer
                  pixels. Brush wraps at tile edges for seamless patterns.
                  "Tile Preview" toggle shows the replicated result on the
                  canvas with seam guides.
  - FULL CANVAS : draw directly on the full 8520x4320 grid.
  - IMAGE       : import a bitmap and tune the threshold / dithering /
                  placement in a live-preview dialog, then paint on top.

Save Mask PNG produces the 2840x4320 RGB-encoded PNG you load via HDMI.
Mouse: L paint, R erase, M-drag pan, wheel scroll, Ctrl+wheel zoom.

Requires: numpy, Pillow.   Install:  pip install numpy pillow
"""

import os
import zlib
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageTk


# -------- Panel geometry --------
LCD_WIDTH      = 8520
LCD_HEIGHT     = 4320
H_COMPRESSION  = 3
OUTPUT_WIDTH   = LCD_WIDTH // H_COMPRESSION    # 2840
OUTPUT_HEIGHT  = LCD_HEIGHT                    # 4320
SUBPIXEL_ORDER = "RGB"                         # "RGB" or "BGR"

# -------- Tile geometry --------
# Horizontal and vertical division counts are chosen from factors of the
# panel dimensions so each tile is an exact integer size. Minimum tile
# size is 100 px in each axis to keep things sensible.
MIN_TILE_PX = 100

def _factors(n, min_tile):
    return [d for d in range(1, n + 1)
            if n % d == 0 and n // d >= min_tile]

# 8520 = 2^3 * 3 * 5 * 71
HORIZ_DIVISIONS = _factors(LCD_WIDTH,  MIN_TILE_PX)
# [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 24, 30, 40, 60, 71]
# 4320 = 2^5 * 3^3 * 5
VERT_DIVISIONS  = _factors(LCD_HEIGHT, MIN_TILE_PX)
# [1, 2, 3, 4, 5, 6, 8, 9, 10, 12, 15, 16, 18, 20, 24, 27, 30, 32, 36, 40]

DEFAULT_TILE_N = 4
DEFAULT_TILE_M = 4

# -------- Theme --------
T = {
    'bg':         '#0a0a14',
    'panel':      '#14141f',
    'panel2':     '#1a1a28',
    'btn':        '#1f1f2e',
    'btn_h':      '#2a2a3e',
    'btn_a':      '#3a2a5a',
    'accent':     '#b855ff',
    'accent_b':   '#d8a0ff',
    'accent_d':   '#6b3399',
    'text':       '#e8e8f0',
    'text_d':     '#8a8aa0',
    'border':     '#2a1f44',
    'border_b':   '#5a3a8a',
    'cnv_bg':     '#0d0d18',
    'grid':       '#1f1f30',
    'seam':       '#7a4ac8',
    'danger':     '#ff5577',
    'success':    '#6affb0',
}

MODE_TILE  = 'tile'
MODE_FULL  = 'full'
MODE_IMAGE = 'image'

FONT_BASE  = ('Segoe UI', 9) if os.name == 'nt' else ('Helvetica', 10)
FONT_BOLD  = (FONT_BASE[0], FONT_BASE[1], 'bold')
FONT_TITLE = (FONT_BASE[0], 13, 'bold')
FONT_TAB   = (FONT_BASE[0], 10, 'bold')

# Pillow constants (handle old/new API)
try:
    RES_LANCZOS = Image.Resampling.LANCZOS
    RES_NEAREST = Image.Resampling.NEAREST
except AttributeError:
    RES_LANCZOS = Image.LANCZOS
    RES_NEAREST = Image.NEAREST
try:
    DITHER_FS = Image.Dither.FLOYDSTEINBERG
    DITHER_NONE = Image.Dither.NONE
except AttributeError:
    DITHER_FS = Image.FLOYDSTEINBERG
    DITHER_NONE = Image.NONE


# ============================================================
# Styled widget factories
# ============================================================
def mk_btn(parent, text, command, kind='normal', width=None):
    b = tk.Button(parent, text=text, command=command,
                  relief=tk.FLAT, borderwidth=0, highlightthickness=0,
                  cursor='hand2', padx=12, pady=6, font=FONT_BASE)
    if width is not None:
        b.config(width=width)
    if kind == 'accent':
        b.config(bg=T['accent'], fg=T['bg'],
                 activebackground=T['accent_b'], activeforeground=T['bg'])
    elif kind == 'ghost':
        b.config(bg=T['bg'], fg=T['text_d'],
                 activebackground=T['btn_h'], activeforeground=T['text'])
    else:
        b.config(bg=T['btn'], fg=T['text'],
                 activebackground=T['btn_h'], activeforeground=T['text'])
    return b


def mk_lbl(parent, text, dim=False, bg=None, font=None):
    return tk.Label(parent, text=text,
                    bg=(bg if bg is not None else T['panel']),
                    fg=T['text_d'] if dim else T['text'],
                    font=(font or FONT_BASE))


def mk_chk(parent, text, var, command=None, bg=None):
    bg = bg if bg is not None else T['panel']
    return tk.Checkbutton(parent, text=text, variable=var, command=command,
                          bg=bg, fg=T['text'],
                          selectcolor=T['btn_a'],
                          activebackground=bg,
                          activeforeground=T['accent_b'],
                          relief=tk.FLAT, borderwidth=0, highlightthickness=0,
                          font=FONT_BASE, cursor='hand2',
                          padx=2)


def mk_spin(parent, from_, to, var, width=6, increment=1):
    return tk.Spinbox(parent, from_=from_, to=to, increment=increment,
                      width=width, textvariable=var,
                      bg=T['btn'], fg=T['text'],
                      insertbackground=T['accent'],
                      buttonbackground=T['btn_h'],
                      relief=tk.FLAT, borderwidth=0,
                      highlightthickness=1,
                      highlightbackground=T['border'],
                      highlightcolor=T['accent'],
                      font=FONT_BASE)


def mk_scale(parent, from_, to, var, command=None, length=200, bg=None):
    bg = bg if bg is not None else T['panel']
    return tk.Scale(parent, from_=from_, to=to, variable=var, command=command,
                    orient=tk.HORIZONTAL, length=length,
                    bg=bg, fg=T['text_d'],
                    troughcolor=T['btn'],
                    activebackground=T['accent_b'],
                    highlightthickness=0, borderwidth=0,
                    relief=tk.FLAT, sliderrelief=tk.FLAT,
                    font=FONT_BASE, showvalue=True)


def mk_sep_v(parent, bg_outer=None):
    bg_outer = bg_outer if bg_outer is not None else T['panel']
    f = tk.Frame(parent, bg=bg_outer)
    tk.Frame(f, bg=T['border'], width=1).pack(side=tk.LEFT, fill=tk.Y, pady=8)
    return f


def mk_sep_h(parent, bg_outer=None):
    bg_outer = bg_outer if bg_outer is not None else T['panel']
    f = tk.Frame(parent, bg=bg_outer)
    tk.Frame(f, bg=T['border'], height=1).pack(fill=tk.X, padx=4)
    return f


# ============================================================
# Image Import Dialog
# ============================================================
class ImageImportDialog:
    """Modal dialog with live preview for converting an image to a binary
    mask at LCD resolution. Calls on_apply(mask_uint8, params_dict) when
    the user clicks Apply."""

    PREV_W = 760
    PREV_H = 380  # LCD aspect is ~2:1

    def __init__(self, parent, source_pil, on_apply, existing_params=None):
        self.parent = parent
        self.source = source_pil.convert('L')   # grayscale once
        self.on_apply = on_apply

        p = existing_params or {}
        self.rotation_str = tk.StringVar(value=str(p.get('rotation', 0)))
        self.fit_mode     = tk.StringVar(value=p.get('fit_mode', 'fit'))
        self.scale_pct    = tk.IntVar(value=p.get('scale_pct', 100))
        self.offset_x     = tk.IntVar(value=p.get('offset_x', 0))
        self.offset_y     = tk.IntVar(value=p.get('offset_y', 0))
        self.threshold    = tk.IntVar(value=p.get('threshold', 128))
        self.invert       = tk.BooleanVar(value=p.get('invert', False))
        self.dither       = tk.StringVar(value=p.get('dither', 'none'))

        self._preview_after = None
        self._photo = None

        self.dlg = tk.Toplevel(parent)
        self.dlg.title("Image to Mask")
        self.dlg.configure(bg=T['bg'])
        self.dlg.geometry("1100x600")
        self.dlg.transient(parent)
        self.dlg.grab_set()

        self._build_ui()

        # Live-update traces
        for v in (self.rotation_str, self.fit_mode, self.scale_pct,
                  self.offset_x, self.offset_y, self.threshold,
                  self.invert, self.dither):
            v.trace_add('write', lambda *a: self._schedule_preview())

        self.dlg.after(50, self._update_preview)
        self.dlg.protocol("WM_DELETE_WINDOW", self._cancel)

    # ---------- UI ----------
    def _build_ui(self):
        # Left: preview pane
        left = tk.Frame(self.dlg, bg=T['bg'], padx=18, pady=18)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        mk_lbl(left, "LIVE PREVIEW",
               bg=T['bg'], font=FONT_BOLD).pack(anchor=tk.W)
        mk_lbl(left,
               f"{LCD_WIDTH}×{LCD_HEIGHT} mask, shown downsampled",
               dim=True, bg=T['bg']).pack(anchor=tk.W, pady=(2, 10))

        canvas_holder = tk.Frame(left, bg=T['border_b'], padx=1, pady=1)
        canvas_holder.pack()
        self.preview_canvas = tk.Canvas(
            canvas_holder, bg=T['cnv_bg'], highlightthickness=0,
            width=self.PREV_W, height=self.PREV_H)
        self.preview_canvas.pack()

        self.info_label = mk_lbl(left, "", dim=True, bg=T['bg'])
        self.info_label.pack(anchor=tk.W, pady=(10, 0))

        # Right: controls
        right = tk.Frame(self.dlg, bg=T['panel'], padx=18, pady=18,
                         width=300)
        right.pack(side=tk.RIGHT, fill=tk.Y)
        right.pack_propagate(False)

        mk_lbl(right, "PLACEMENT",
               bg=T['panel'], font=FONT_BOLD).pack(anchor=tk.W)
        mk_sep_h(right).pack(fill=tk.X, pady=(4, 10))

        # Fit mode
        row = tk.Frame(right, bg=T['panel'])
        row.pack(fill=tk.X, pady=3)
        mk_lbl(row, "Fit", bg=T['panel']).pack(side=tk.LEFT)
        fit_cb = ttk.Combobox(row, textvariable=self.fit_mode,
                              values=['fit', 'fill', 'stretch'],
                              state='readonly', width=12, font=FONT_BASE)
        fit_cb.pack(side=tk.RIGHT)

        # Rotation
        row = tk.Frame(right, bg=T['panel'])
        row.pack(fill=tk.X, pady=3)
        mk_lbl(row, "Rotation", bg=T['panel']).pack(side=tk.LEFT)
        rot_cb = ttk.Combobox(row, textvariable=self.rotation_str,
                              values=['0', '90', '180', '270'],
                              state='readonly', width=12, font=FONT_BASE)
        rot_cb.pack(side=tk.RIGHT)

        # Scale
        mk_lbl(right, "Scale (%)", dim=True,
               bg=T['panel']).pack(anchor=tk.W, pady=(10, 0))
        mk_scale(right, 5, 400, self.scale_pct,
                 length=260, bg=T['panel']).pack()

        # Offset X
        row = tk.Frame(right, bg=T['panel'])
        row.pack(fill=tk.X, pady=3)
        mk_lbl(row, "Offset X (LCD px)", bg=T['panel']).pack(side=tk.LEFT)
        mk_spin(row, -LCD_WIDTH, LCD_WIDTH,
                self.offset_x, width=8).pack(side=tk.RIGHT)

        # Offset Y
        row = tk.Frame(right, bg=T['panel'])
        row.pack(fill=tk.X, pady=3)
        mk_lbl(row, "Offset Y (LCD px)", bg=T['panel']).pack(side=tk.LEFT)
        mk_spin(row, -LCD_HEIGHT, LCD_HEIGHT,
                self.offset_y, width=8).pack(side=tk.RIGHT)

        # Center button
        mk_btn(right, "Re-center",
               lambda: (self.offset_x.set(0), self.offset_y.set(0))
               ).pack(anchor=tk.E, pady=(6, 0))

        mk_lbl(right, "BINARIZATION",
               bg=T['panel'], font=FONT_BOLD).pack(anchor=tk.W,
                                                   pady=(18, 0))
        mk_sep_h(right).pack(fill=tk.X, pady=(4, 10))

        mk_lbl(right, "Threshold (0-255)", dim=True,
               bg=T['panel']).pack(anchor=tk.W)
        mk_scale(right, 0, 255, self.threshold,
                 length=260, bg=T['panel']).pack()

        mk_chk(right, "Invert (light = transparent)",
               self.invert, bg=T['panel']).pack(anchor=tk.W, pady=4)

        row = tk.Frame(right, bg=T['panel'])
        row.pack(fill=tk.X, pady=3)
        mk_lbl(row, "Dither", bg=T['panel']).pack(side=tk.LEFT)
        dith_cb = ttk.Combobox(row, textvariable=self.dither,
                               values=['none', 'floyd-steinberg'],
                               state='readonly', width=16, font=FONT_BASE)
        dith_cb.pack(side=tk.RIGHT)

        # Action buttons
        mk_sep_h(right).pack(fill=tk.X, pady=(20, 12))
        btn_row = tk.Frame(right, bg=T['panel'])
        btn_row.pack(fill=tk.X)
        mk_btn(btn_row, "Cancel",
               self._cancel).pack(side=tk.LEFT, padx=2)
        mk_btn(btn_row, "Apply Mask", self._apply,
               kind='accent').pack(side=tk.RIGHT, padx=2)

    # ---------- Preview ----------
    def _schedule_preview(self):
        if self._preview_after is not None:
            try: self.dlg.after_cancel(self._preview_after)
            except Exception: pass
        self._preview_after = self.dlg.after(40, self._update_preview)

    def _update_preview(self):
        self._preview_after = None
        params = self._collect()
        mask = self._process(params, preview=True)
        img = Image.fromarray(mask * 255, mode='L').convert('RGB')
        img = img.resize((self.PREV_W, self.PREV_H), RES_NEAREST)
        self._photo = ImageTk.PhotoImage(img)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(0, 0, image=self._photo,
                                         anchor=tk.NW)
        # Update info
        on_pct = float(mask.mean()) * 100
        sw, sh = self.source.size
        self.info_label.config(
            text=f"Source {sw}×{sh}  •  Transparent area: {on_pct:.1f}%  "
                 f"•  Threshold {params['threshold']}  "
                 f"•  Dither: {params['dither']}")

    # ---------- Conversion ----------
    def _collect(self):
        try: rot = int(self.rotation_str.get())
        except (ValueError, tk.TclError): rot = 0
        return {
            'rotation':  rot,
            'fit_mode':  self.fit_mode.get(),
            'scale_pct': self.scale_pct.get(),
            'offset_x':  self.offset_x.get(),
            'offset_y':  self.offset_y.get(),
            'threshold': self.threshold.get(),
            'invert':    self.invert.get(),
            'dither':    self.dither.get(),
        }

    def _process(self, params, preview=False):
        """Returns binary mask (np.uint8 with values 0 or 1)."""
        if preview:
            target_w, target_h = self.PREV_W, self.PREV_H
        else:
            target_w, target_h = LCD_WIDTH, LCD_HEIGHT

        # Scale factor relating LCD-pixel offsets to current target size
        scale_to_target = target_w / LCD_WIDTH

        # Rotate source
        img = self.source
        if params['rotation']:
            img = img.rotate(-params['rotation'], expand=True, fillcolor=0)
        src_w, src_h = img.size

        # Compute placement size based on fit mode
        s = params['scale_pct'] / 100.0
        mode = params['fit_mode']
        if mode == 'stretch':
            new_w = max(1, int(target_w * s))
            new_h = max(1, int(target_h * s))
        else:
            if mode == 'fill':
                r = max(target_w / src_w, target_h / src_h) * s
            else:  # 'fit'
                r = min(target_w / src_w, target_h / src_h) * s
            new_w = max(1, int(src_w * r))
            new_h = max(1, int(src_h * r))

        img2 = img.resize((new_w, new_h), RES_LANCZOS)

        x = (target_w - new_w) // 2 + int(params['offset_x'] * scale_to_target)
        y = (target_h - new_h) // 2 + int(params['offset_y'] * scale_to_target)

        # Composite onto black canvas
        canvas = Image.new('L', (target_w, target_h), 0)
        canvas.paste(img2, (x, y))

        # Adjust brightness so threshold maps to 128, then binarize/dither
        gray = np.array(canvas).astype(np.int16)
        if params['invert']:
            gray = 255 - gray
        gray = np.clip(gray + (128 - params['threshold']), 0, 255).astype(np.uint8)

        if params['dither'] == 'floyd-steinberg':
            binary = Image.fromarray(gray).convert('1', dither=DITHER_FS)
            mask = (np.array(binary) > 0).astype(np.uint8)
        else:
            mask = (gray >= 128).astype(np.uint8)

        return mask

    # ---------- Actions ----------
    def _apply(self):
        params = self._collect()
        mask = self._process(params, preview=False)
        self.on_apply(mask, params)
        self.dlg.destroy()

    def _cancel(self):
        self.dlg.destroy()


# ============================================================
# Main Application
# ============================================================
class MaskGenerator:
    def __init__(self, root):
        self.root = root
        self.root.title("UV Lithography Mask Generator")
        self.root.geometry("1320x840")
        self.root.configure(bg=T['bg'])
        self._apply_ttk_theme()

        # ---- Mode + per-mode patterns ----
        self.mode = MODE_TILE
        self.tile_n = DEFAULT_TILE_N
        self.tile_m = DEFAULT_TILE_M
        self.tile_n_var = tk.IntVar(value=self.tile_n)
        self.tile_m_var = tk.IntVar(value=self.tile_m)
        self.pattern_tile  = np.zeros((self._tile_h(), self._tile_w()), dtype=np.uint8)
        self.pattern_full  = np.zeros((LCD_HEIGHT, LCD_WIDTH), dtype=np.uint8)
        self.pattern_image = np.zeros((LCD_HEIGHT, LCD_WIDTH), dtype=np.uint8)

        # ---- Undo history per mode ----
        self.history = {MODE_TILE: [], MODE_FULL: [], MODE_IMAGE: []}
        self.hidx = {MODE_TILE: -1, MODE_FULL: -1, MODE_IMAGE: -1}
        self.MAX_HISTORY = 40

        # ---- View state ----
        self.pixel_size = 0.5

        # ---- Common ----
        self.brush_var      = tk.IntVar(value=3)
        self.subpixel_mode  = tk.BooleanVar(value=True)
        self.invert_output  = tk.BooleanVar(value=False)
        self.show_grid      = tk.BooleanVar(value=False)
        self.tile_preview   = tk.BooleanVar(value=False)

        # ---- Image source / params ----
        self.image_source = None
        self.image_params = None

        # ---- Internal state ----
        self.mouse_down = False
        self._dirty_after = None
        self._tile_cache = None
        self._photo = None

        self._build_ui()
        for m in (MODE_TILE, MODE_FULL, MODE_IMAGE):
            self._snapshot(m)
        self.root.after(100, self._fit_to_canvas)

    # ---------- ttk theme tweaks ----------
    def _apply_ttk_theme(self):
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass
        style.configure('TCombobox',
                        fieldbackground=T['btn'], background=T['btn'],
                        foreground=T['text'], arrowcolor=T['accent_b'],
                        bordercolor=T['border'], lightcolor=T['border'],
                        darkcolor=T['border'], borderwidth=1,
                        relief=tk.FLAT)
        style.map('TCombobox',
                  fieldbackground=[('readonly', T['btn'])],
                  selectbackground=[('readonly', T['btn'])],
                  selectforeground=[('readonly', T['text'])],
                  bordercolor=[('focus', T['accent'])])
        style.configure('Vertical.TScrollbar',
                        background=T['panel'], troughcolor=T['bg'],
                        bordercolor=T['bg'], arrowcolor=T['text_d'],
                        relief=tk.FLAT)
        style.configure('Horizontal.TScrollbar',
                        background=T['panel'], troughcolor=T['bg'],
                        bordercolor=T['bg'], arrowcolor=T['text_d'],
                        relief=tk.FLAT)
        self.root.option_add('*TCombobox*Listbox.background', T['panel'])
        self.root.option_add('*TCombobox*Listbox.foreground', T['text'])
        self.root.option_add('*TCombobox*Listbox.selectBackground', T['accent'])
        self.root.option_add('*TCombobox*Listbox.selectForeground', T['bg'])
        self.root.option_add('*TCombobox*Listbox.font', FONT_BASE)

    # ============================================================
    # UI Construction
    # ============================================================
    def _build_ui(self):
        # ---- Header strip ----
        header = tk.Frame(self.root, bg=T['bg'], height=64)
        header.pack(side=tk.TOP, fill=tk.X)
        header.pack_propagate(False)

        title = tk.Label(header, text="◆ UV LITHO MASK",
                         bg=T['bg'], fg=T['accent'], font=FONT_TITLE,
                         padx=20)
        title.pack(side=tk.LEFT)

        subtitle = tk.Label(header,
                            text=f"{LCD_WIDTH}×{LCD_HEIGHT} panel  •  "
                                 f"{OUTPUT_WIDTH}×{OUTPUT_HEIGHT} HDMI",
                            bg=T['bg'], fg=T['text_d'], font=FONT_BASE)
        subtitle.pack(side=tk.LEFT, padx=(0, 30))

        # Mode tabs (pill style)
        tabs = tk.Frame(header, bg=T['bg'])
        tabs.pack(side=tk.LEFT)

        self.tab_buttons = []
        for mode_val, label in [
            (MODE_TILE,  "  TILE  "),
            (MODE_FULL,  "  FULL CANVAS  "),
            (MODE_IMAGE, "  IMAGE IMPORT  ")]:
            b = tk.Button(tabs, text=label,
                          relief=tk.FLAT, borderwidth=0,
                          highlightthickness=0, cursor='hand2',
                          padx=4, pady=10, font=FONT_TAB,
                          command=lambda m=mode_val: self._switch_mode(m))
            b.pack(side=tk.LEFT, padx=3)
            self.tab_buttons.append((mode_val, b))

        # Right-side header buttons
        mk_btn(header, "Test Patterns",
               self._test_pattern_menu, kind='ghost').pack(
            side=tk.RIGHT, padx=(2, 20))

        # ---- Top accent strip (neon line) ----
        tk.Frame(self.root, bg=T['accent_d'], height=1).pack(fill=tk.X)
        tk.Frame(self.root, bg=T['border_b'], height=1).pack(fill=tk.X)

        # ---- Toolbar ----
        self.toolbar = tk.Frame(self.root, bg=T['panel'], height=48)
        self.toolbar.pack(side=tk.TOP, fill=tk.X)
        self.toolbar.pack_propagate(False)

        # ---- Output bar ----
        outbar = tk.Frame(self.root, bg=T['panel2'], height=44)
        outbar.pack(side=tk.TOP, fill=tk.X)
        outbar.pack_propagate(False)

        mk_chk(outbar, "Subpixel encode", self.subpixel_mode,
               bg=T['panel2']).pack(side=tk.LEFT, padx=(20, 8))
        mk_chk(outbar, "Invert output", self.invert_output,
               bg=T['panel2']).pack(side=tk.LEFT, padx=4)

        mk_btn(outbar, "Save Mask PNG",
               self._save_png, kind='accent').pack(side=tk.RIGHT,
                                                   padx=(4, 14))
        mk_btn(outbar, "Load Project",
               self._load_project).pack(side=tk.RIGHT, padx=2)
        mk_btn(outbar, "Save Project",
               self._save_project).pack(side=tk.RIGHT, padx=2)

        tk.Frame(self.root, bg=T['border'], height=1).pack(fill=tk.X)

        # ---- Canvas area ----
        canvas_frame = tk.Frame(self.root, bg=T['bg'])
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(canvas_frame, bg=T['cnv_bg'],
                                highlightthickness=0)
        self.hbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL,
                                  command=self.canvas.xview)
        self.vbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL,
                                  command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self._xset,
                              yscrollcommand=self._yset)
        self.vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.hbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Canvas bindings
        self.canvas.bind("<Button-1>",        lambda e: self._press(e, 1))
        self.canvas.bind("<Button-3>",        lambda e: self._press(e, 0))
        self.canvas.bind("<B1-Motion>",       lambda e: self._drag(e, 1))
        self.canvas.bind("<B3-Motion>",       lambda e: self._drag(e, 0))
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<ButtonRelease-3>", self._release)
        self.canvas.bind("<Motion>",          self._update_status)
        self.canvas.bind("<Configure>",       lambda e: self._request_render())
        self.canvas.bind("<Button-2>",        self._pan_start)
        self.canvas.bind("<B2-Motion>",       self._pan_move)
        self.canvas.bind("<MouseWheel>",         self._on_wheel)
        self.canvas.bind("<Control-MouseWheel>", self._on_ctrl_wheel)
        self.canvas.bind("<Shift-MouseWheel>",   self._on_shift_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._wheel_linux(e, 1))
        self.canvas.bind("<Button-5>", lambda e: self._wheel_linux(e, -1))

        # ---- Status bar ----
        self.status = tk.Label(self.root, text="Ready", anchor=tk.W,
                               bg=T['panel'], fg=T['text_d'],
                               padx=14, pady=5, font=FONT_BASE,
                               relief=tk.FLAT)
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

        # ---- Keyboard shortcuts ----
        self.root.bind("<Control-z>", lambda e: self._undo())
        self.root.bind("<Control-y>", lambda e: self._redo())
        self.root.bind("<Control-s>", lambda e: self._save_png())
        self.root.bind("<Control-Key-1>", lambda e: self._switch_mode(MODE_TILE))
        self.root.bind("<Control-Key-2>", lambda e: self._switch_mode(MODE_FULL))
        self.root.bind("<Control-Key-3>", lambda e: self._switch_mode(MODE_IMAGE))

        self._update_tab_styles()
        self._build_toolbar()

    def _build_toolbar(self):
        for w in self.toolbar.winfo_children():
            w.destroy()

        # Brush
        mk_lbl(self.toolbar, "BRUSH",
               bg=T['panel'], font=FONT_BOLD).pack(side=tk.LEFT, padx=(20, 6))
        mk_spin(self.toolbar, 1, 100,
                self.brush_var, width=4).pack(side=tk.LEFT)

        mk_sep_v(self.toolbar).pack(side=tk.LEFT, padx=10)

        mk_chk(self.toolbar, "Grid", self.show_grid,
               command=self._render).pack(side=tk.LEFT, padx=4)

        if self.mode == MODE_TILE:
            mk_sep_v(self.toolbar).pack(side=tk.LEFT, padx=10)
            mk_lbl(self.toolbar, "TILES",
                   bg=T['panel'], font=FONT_BOLD).pack(side=tk.LEFT, padx=(2, 6))

            n_cb = ttk.Combobox(
                self.toolbar, textvariable=self.tile_n_var,
                values=[str(v) for v in HORIZ_DIVISIONS],
                state='readonly', width=4, font=FONT_BASE)
            n_cb.pack(side=tk.LEFT)
            mk_lbl(self.toolbar, "×",
                   bg=T['panel'], dim=True).pack(side=tk.LEFT, padx=4)
            m_cb = ttk.Combobox(
                self.toolbar, textvariable=self.tile_m_var,
                values=[str(v) for v in VERT_DIVISIONS],
                state='readonly', width=4, font=FONT_BASE)
            m_cb.pack(side=tk.LEFT)
            n_cb.bind("<<ComboboxSelected>>", self._change_tile_dims)
            m_cb.bind("<<ComboboxSelected>>", self._change_tile_dims)

            self.tile_info_label = tk.Label(
                self.toolbar, text="",
                bg=T['panel'], fg=T['accent_b'], font=FONT_BASE,
                padx=12)
            self.tile_info_label.pack(side=tk.LEFT)
            self._update_tile_info()

            mk_sep_v(self.toolbar).pack(side=tk.LEFT, padx=10)
            mk_chk(self.toolbar, "Tile Preview",
                   self.tile_preview,
                   command=self._on_tile_preview_change).pack(side=tk.LEFT, padx=4)

        if self.mode == MODE_IMAGE:
            mk_sep_v(self.toolbar).pack(side=tk.LEFT, padx=10)
            mk_btn(self.toolbar, "Import Image…",
                   self._import_image, kind='accent').pack(side=tk.LEFT, padx=4)
            if self.image_source is not None:
                mk_btn(self.toolbar, "Re-tune Settings",
                       self._retune_image).pack(side=tk.LEFT, padx=4)

        # Right: clear/undo/zoom
        mk_btn(self.toolbar, "Fit",
               self._fit_to_canvas).pack(side=tk.RIGHT, padx=(2, 20))
        mk_btn(self.toolbar, "1:1",
               lambda: self._set_zoom(1.0)).pack(side=tk.RIGHT, padx=1)
        mk_btn(self.toolbar, "+",
               lambda: self._zoom(1.25), width=3).pack(side=tk.RIGHT, padx=1)
        mk_btn(self.toolbar, "−",
               lambda: self._zoom(0.8), width=3).pack(side=tk.RIGHT, padx=1)

        mk_sep_v(self.toolbar).pack(side=tk.RIGHT, padx=10)

        mk_btn(self.toolbar, "Redo",
               self._redo).pack(side=tk.RIGHT, padx=2)
        mk_btn(self.toolbar, "Undo",
               self._undo).pack(side=tk.RIGHT, padx=2)
        mk_btn(self.toolbar, "Clear",
               self._clear).pack(side=tk.RIGHT, padx=(8, 4))

    def _update_tab_styles(self):
        for mv, b in self.tab_buttons:
            if mv == self.mode:
                b.config(bg=T['accent'], fg=T['bg'],
                         activebackground=T['accent_b'],
                         activeforeground=T['bg'])
            else:
                b.config(bg=T['btn'], fg=T['text_d'],
                         activebackground=T['btn_h'],
                         activeforeground=T['text'])

    # ============================================================
    # Mode switching
    # ============================================================
    def _switch_mode(self, new_mode):
        if self.mode == new_mode: return
        self.mode = new_mode
        self._tile_cache = None
        self._update_tab_styles()
        self._build_toolbar()
        self._fit_to_canvas()
        self._set_status_idle()

    def _on_tile_preview_change(self):
        self._tile_cache = None
        self._fit_to_canvas()

    # ============================================================
    # Pattern access
    # ============================================================
    def _tile_w(self):
        return LCD_WIDTH // self.tile_n

    def _tile_h(self):
        return LCD_HEIGHT // self.tile_m

    def _active(self):
        if self.mode == MODE_TILE:  return self.pattern_tile
        if self.mode == MODE_FULL:  return self.pattern_full
        return self.pattern_image

    def _set_active(self, arr):
        if self.mode == MODE_TILE:  self.pattern_tile = arr
        elif self.mode == MODE_FULL: self.pattern_full = arr
        else: self.pattern_image = arr
        self._tile_cache = None

    def _display_dims(self):
        if self.mode == MODE_TILE and self.tile_preview.get():
            return LCD_WIDTH, LCD_HEIGHT
        if self.mode == MODE_TILE:
            return self._tile_w(), self._tile_h()
        return LCD_WIDTH, LCD_HEIGHT

    def _display_pattern(self):
        if self.mode == MODE_TILE and self.tile_preview.get():
            if self._tile_cache is None:
                self._tile_cache = np.tile(self.pattern_tile,
                                           (self.tile_m, self.tile_n))
            return self._tile_cache
        return self._active()

    def _change_tile_dims(self, *args):
        """Called when the N or M dropdown changes. Resizes the tile
        pattern via nearest-neighbor to preserve the visual design."""
        try:
            new_n = int(self.tile_n_var.get())
            new_m = int(self.tile_m_var.get())
        except (ValueError, tk.TclError):
            return
        if new_n not in HORIZ_DIVISIONS or new_m not in VERT_DIVISIONS:
            return
        if new_n == self.tile_n and new_m == self.tile_m:
            return
        new_w = LCD_WIDTH  // new_n
        new_h = LCD_HEIGHT // new_m
        if self.pattern_tile.any():
            img = Image.fromarray(self.pattern_tile * 255, mode='L')
            img = img.resize((new_w, new_h), RES_NEAREST)
            self.pattern_tile = (np.array(img) > 0).astype(np.uint8)
        else:
            self.pattern_tile = np.zeros((new_h, new_w), dtype=np.uint8)
        self.tile_n = new_n
        self.tile_m = new_m
        # Tile dims changed => old undo blobs have wrong shape, reset
        self.history[MODE_TILE] = []
        self.hidx[MODE_TILE] = -1
        self._snapshot(MODE_TILE)
        self._tile_cache = None
        self._update_tile_info()
        if self.mode == MODE_TILE:
            self._fit_to_canvas()

    def _update_tile_info(self):
        if not hasattr(self, 'tile_info_label'):
            return
        if not self.tile_info_label.winfo_exists():
            return
        tw, th = self._tile_w(), self._tile_h()
        total = self.tile_n * self.tile_m
        aligned = (tw % 3 == 0)
        marker = "◉" if aligned else "◌"
        align_txt = ("subpixel-aligned" if aligned
                     else "subpixel phase shifts at seams")
        self.tile_info_label.config(
            text=f"{tw}×{th} px  •  {total} tiles  •  {marker} {align_txt}",
            fg=(T['accent_b'] if aligned else T['text_d']))

    # ============================================================
    # Rendering (viewport-aware)
    # ============================================================
    def _xset(self, *a):
        self.hbar.set(*a); self._request_render()

    def _yset(self, *a):
        self.vbar.set(*a); self._request_render()

    def _request_render(self):
        if self._dirty_after is None:
            self._dirty_after = self.root.after(15, self._render)

    def _render(self):
        if self._dirty_after is not None:
            try: self.root.after_cancel(self._dirty_after)
            except Exception: pass
            self._dirty_after = None

        self.canvas.delete("all")
        ps = self.pixel_size
        dw, dh = self._display_dims()
        total_w = max(1, int(dw * ps))
        total_h = max(1, int(dh * ps))
        self.canvas.configure(scrollregion=(0, 0, total_w, total_h))

        cw = self.canvas.winfo_width(); ch = self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            self.root.after(50, self._render); return

        # Visible region in display coords
        xv = self.canvas.xview(); yv = self.canvas.yview()
        vx0 = int(xv[0] * total_w); vy0 = int(yv[0] * total_h)
        vx1 = int(xv[1] * total_w) + 1; vy1 = int(yv[1] * total_h) + 1
        margin = max(2, int(ps * 8))
        vx0 = max(0, vx0 - margin); vy0 = max(0, vy0 - margin)
        vx1 = min(total_w, vx1 + margin); vy1 = min(total_h, vy1 + margin)

        px0 = max(0, int(vx0 / ps))
        py0 = max(0, int(vy0 / ps))
        px1 = min(dw, int(vx1 / ps) + 1)
        py1 = min(dh, int(vy1 / ps) + 1)
        if px1 <= px0 or py1 <= py0: return

        disp = self._display_pattern()
        sub = disp[py0:py1, px0:px1]
        out_w = max(1, int((px1 - px0) * ps))
        out_h = max(1, int((py1 - py0) * ps))
        img = Image.fromarray(sub * 255, mode='L')
        img = img.resize((out_w, out_h), RES_NEAREST)
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.create_image(int(px0 * ps), int(py0 * ps),
                                 image=self._photo, anchor=tk.NW)

        # Grid lines (only at high zoom)
        if self.show_grid.get() and ps >= 4:
            y_top = int(py0 * ps); y_bot = int(py1 * ps)
            x_lft = int(px0 * ps); x_rgt = int(px1 * ps)
            for i in range(px0, px1 + 1):
                x = int(i * ps)
                self.canvas.create_line(x, y_top, x, y_bot, fill=T['grid'])
            for i in range(py0, py1 + 1):
                y = int(i * ps)
                self.canvas.create_line(x_lft, y, x_rgt, y, fill=T['grid'])

        # Tile seams (dashed neon lines) when tile-preview is on
        if self.mode == MODE_TILE and self.tile_preview.get():
            tw = self._tile_w(); th = self._tile_h()
            for i in range(1, self.tile_n):
                x = int(i * tw * ps)
                self.canvas.create_line(x, 0, x, total_h,
                                        fill=T['seam'], dash=(6, 4),
                                        width=1)
            for j in range(1, self.tile_m):
                y = int(j * th * ps)
                self.canvas.create_line(0, y, total_w, y,
                                        fill=T['seam'], dash=(6, 4),
                                        width=1)

    # ============================================================
    # Painting
    # ============================================================
    def _evt_to_disp(self, e):
        x = int(self.canvas.canvasx(e.x) / self.pixel_size)
        y = int(self.canvas.canvasy(e.y) / self.pixel_size)
        return x, y

    def _paint_at_display(self, dx, dy, val):
        """Returns True if the pattern changed."""
        r = max(0, self.brush_var.get() // 2)

        if self.mode == MODE_TILE:
            tw = self._tile_w(); th = self._tile_h()
            # Wrap in tile coords for seamless edges
            if self.tile_preview.get():
                cx = dx % tw; cy = dy % th
            else:
                cx, cy = dx, dy
            b = 2 * r + 1
            xs = (np.arange(b) - r + cx) % tw
            ys = (np.arange(b) - r + cy) % th
            self.pattern_tile[np.ix_(ys, xs)] = val
            self._tile_cache = None
            return True
        else:
            pat = self._active()
            h, w = pat.shape
            x0 = max(0, dx - r); y0 = max(0, dy - r)
            x1 = min(w, dx + r + 1); y1 = min(h, dy + r + 1)
            if x1 > x0 and y1 > y0:
                pat[y0:y1, x0:x1] = val
                return True
        return False

    def _press(self, e, val):
        self.mouse_down = True
        if self._paint_at_display(*self._evt_to_disp(e), val):
            self._request_render()

    def _drag(self, e, val):
        if not self.mouse_down: return
        x, y = self._evt_to_disp(e)
        dw, dh = self._display_dims()
        if 0 <= x < dw and 0 <= y < dh:
            if self._paint_at_display(x, y, val):
                self._request_render()

    def _release(self, e):
        if self.mouse_down:
            self.mouse_down = False
            self._render()
            self._snapshot(self.mode)

    # ============================================================
    # Pan / Zoom
    # ============================================================
    def _pan_start(self, e):
        self.canvas.scan_mark(e.x, e.y)

    def _pan_move(self, e):
        self.canvas.scan_dragto(e.x, e.y, gain=1)
        self._request_render()

    def _on_wheel(self, e):
        d = 1 if e.delta > 0 else -1
        self.canvas.yview_scroll(-d * 3, "units")

    def _on_ctrl_wheel(self, e):
        f = 1.25 if e.delta > 0 else 0.8
        self._zoom_at(e.x, e.y, f)

    def _on_shift_wheel(self, e):
        d = 1 if e.delta > 0 else -1
        self.canvas.xview_scroll(-d * 3, "units")

    def _wheel_linux(self, e, direction):
        if e.state & 0x4:
            self._zoom_at(e.x, e.y, 1.25 if direction > 0 else 0.8)
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
        self.pixel_size = max(0.04, min(64.0, self.pixel_size * factor))
        dw, dh = self._display_dims()
        total_w = max(1, int(dw * self.pixel_size))
        total_h = max(1, int(dh * self.pixel_size))
        self.canvas.configure(scrollregion=(0, 0, total_w, total_h))
        new_cx = px * self.pixel_size; new_cy = py * self.pixel_size
        self.canvas.xview_moveto(max(0, (new_cx - sx)) / max(1, total_w))
        self.canvas.yview_moveto(max(0, (new_cy - sy)) / max(1, total_h))
        self._render()

    def _set_zoom(self, val):
        self.pixel_size = val
        self._render()

    def _fit_to_canvas(self):
        self.canvas.update_idletasks()
        cw = self.canvas.winfo_width(); ch = self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            self.root.after(50, self._fit_to_canvas); return
        dw, dh = self._display_dims()
        self.pixel_size = max(0.04, min(cw / dw, ch / dh))
        self.canvas.xview_moveto(0); self.canvas.yview_moveto(0)
        self._render()

    # ============================================================
    # Undo / Redo (compressed history per mode)
    # ============================================================
    def _snapshot(self, mode):
        if mode == MODE_TILE:  arr = self.pattern_tile
        elif mode == MODE_FULL: arr = self.pattern_full
        else: arr = self.pattern_image
        h = self.history[mode]
        hi = self.hidx[mode]
        if hi < len(h) - 1:
            self.history[mode] = h[:hi + 1]
        blob = (arr.shape, zlib.compress(arr.tobytes(), level=1))
        self.history[mode].append(blob)
        if len(self.history[mode]) > self.MAX_HISTORY:
            self.history[mode].pop(0)
        self.hidx[mode] = len(self.history[mode]) - 1

    def _restore(self, mode, idx):
        shape, data = self.history[mode][idx]
        arr = np.frombuffer(zlib.decompress(data),
                            dtype=np.uint8).reshape(shape).copy()
        if mode == MODE_TILE:   self.pattern_tile = arr
        elif mode == MODE_FULL: self.pattern_full = arr
        else: self.pattern_image = arr
        self._tile_cache = None

    def _undo(self):
        m = self.mode
        if self.hidx[m] > 0:
            self.hidx[m] -= 1
            self._restore(m, self.hidx[m])
            self._render()

    def _redo(self):
        m = self.mode
        if self.hidx[m] < len(self.history[m]) - 1:
            self.hidx[m] += 1
            self._restore(m, self.hidx[m])
            self._render()

    def _clear(self):
        label = {MODE_TILE: "the tile", MODE_FULL: "the full canvas",
                 MODE_IMAGE: "the image mask"}[self.mode]
        if messagebox.askyesno("Clear", f"Clear {label}?"):
            arr = np.zeros_like(self._active())
            self._set_active(arr)
            self._snapshot(self.mode)
            self._render()

    # ============================================================
    # Image import
    # ============================================================
    def _import_image(self):
        path = filedialog.askopenfilename(
            title="Choose image to convert",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif"),
                       ("All files", "*.*")])
        if not path: return
        try:
            src = Image.open(path)
            src.load()
        except Exception as ex:
            messagebox.showerror("Load failed", str(ex)); return
        self.image_source = src
        self._open_image_dialog()

    def _retune_image(self):
        if self.image_source is None:
            messagebox.showinfo("No image", "Import an image first.")
            return
        self._open_image_dialog()

    def _open_image_dialog(self):
        def on_apply(mask, params):
            self.pattern_image = mask.astype(np.uint8)
            self.image_params = params
            self._tile_cache = None
            self._snapshot(MODE_IMAGE)
            self._render()
            self.status.config(
                text=f"Image applied  •  {LCD_WIDTH}×{LCD_HEIGHT}  "
                     f"•  threshold {params['threshold']}  "
                     f"•  dither: {params['dither']}")
        ImageImportDialog(self.root, self.image_source, on_apply,
                          self.image_params)
        self._build_toolbar()  # show Re-tune

    # ============================================================
    # Status bar
    # ============================================================
    def _update_status(self, e):
        x, y = self._evt_to_disp(e)
        dw, dh = self._display_dims()
        if not (0 <= x < dw and 0 <= y < dh):
            return
        if self.mode == MODE_TILE:
            tw = self._tile_w(); th = self._tile_h()
            tx = x % tw; ty = y % th
            mode_str = f"TILE  •  tile ({tx},{ty})"
            if self.tile_preview.get():
                mode_str += f"  •  display ({x},{y})"
        else:
            mode_str = f"{self.mode.upper()}  •  LCD ({x},{y})"
        self.status.config(
            text=f"{mode_str}  •  Zoom {self.pixel_size:.3f}×  "
                 f"•  Brush {self.brush_var.get()}  "
                 f"•  Output {OUTPUT_WIDTH}×{OUTPUT_HEIGHT} "
                 f"{'[subpixel]' if self.subpixel_mode.get() else '[plain]'}")

    def _set_status_idle(self):
        tw = self._tile_w(); th = self._tile_h()
        modes = {MODE_TILE: f"TILE  •  drawing on {tw}×{th}, "
                            f"tiles {self.tile_n}×{self.tile_m} "
                            f"→ {LCD_WIDTH}×{LCD_HEIGHT}",
                 MODE_FULL: f"FULL CANVAS  •  {LCD_WIDTH}×{LCD_HEIGHT}",
                 MODE_IMAGE: f"IMAGE IMPORT  •  {LCD_WIDTH}×{LCD_HEIGHT} "
                             f"({'image loaded' if self.image_source else 'no image yet'})"}
        self.status.config(text=modes[self.mode])

    # ============================================================
    # Test patterns (for panel diagnostics)
    # ============================================================
    def _test_pattern_menu(self):
        win = tk.Toplevel(self.root)
        win.title("Diagnostic Patterns")
        win.configure(bg=T['bg'])
        win.transient(self.root)

        tk.Label(win, text="DIAGNOSTIC PATTERNS",
                 bg=T['bg'], fg=T['accent'],
                 font=FONT_TITLE).pack(padx=20, pady=(16, 4))
        tk.Label(win, text="Full-frame 2840×4320 PNGs to verify subpixel addressing.",
                 bg=T['bg'], fg=T['text_d'],
                 font=FONT_BASE).pack(padx=20, pady=(0, 12))

        for name, fn in [
            ("Single column R / G / B (3 files)", self._tp_single_columns),
            ("Solid R / G / B / Y / W (5 files)", self._tp_solid_rgb),
            ("Subpixel resolution chart",          self._tp_resolution_chart),
        ]:
            mk_btn(win, name,
                   lambda f=fn: (f(), win.destroy())).pack(
                fill=tk.X, padx=20, pady=4)
        tk.Frame(win, bg=T['bg'], height=12).pack()

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
        for nm, c in [("R", (255,0,0)), ("G", (0,255,0)),
                      ("B", (0,0,255)), ("Y", (255,255,0)),
                      ("W", (255,255,255))]:
            arr = np.full((OUTPUT_HEIGHT, OUTPUT_WIDTH, 3), c, dtype=np.uint8)
            Image.fromarray(arr).save(os.path.join(d, f"test_solid_{nm}.png"))
        self.status.config(text=f"Solid color tests saved to {d}")

    def _tp_resolution_chart(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=[("PNG", "*.png")],
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
        self.status.config(text=f"Resolution chart → {os.path.basename(path)}")

    # ============================================================
    # Save output
    # ============================================================
    def _build_full_lcd(self):
        """Return an 8520×4320 uint8 array (0/255) for the current mode."""
        if self.mode == MODE_TILE:
            tiled = np.tile(self.pattern_tile, (self.tile_m, self.tile_n))
            return tiled * 255
        elif self.mode == MODE_FULL:
            return self.pattern_full * 255
        else:
            return self.pattern_image * 255

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
            packed = np.maximum.reduce([full[:, 0::3],
                                        full[:, 1::3],
                                        full[:, 2::3]])
            Image.fromarray(packed, mode='L').save(path)

    def _save_png(self):
        if self.mode == MODE_IMAGE and self.image_source is None and \
                not self.pattern_image.any():
            messagebox.showinfo("No mask",
                                "Import an image first, or switch modes.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=[("PNG", "*.png")],
            initialfile=f"mask_{self.mode}.png")
        if not path: return
        self._encode_and_save(self._build_full_lcd(), path)
        encoding = ("subpixel-encoded RGB" if self.subpixel_mode.get()
                    else "plain grayscale")
        self.status.config(
            text=f"Saved {OUTPUT_WIDTH}×{OUTPUT_HEIGHT} {encoding} "
                 f"→ {os.path.basename(path)}")

    # ============================================================
    # Project save / load
    # ============================================================
    def _save_project(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".npz",
            filetypes=[("Project", "*.npz")])
        if not path: return
        np.savez_compressed(
            path,
            tile=self.pattern_tile,
            full=self.pattern_full,
            image=self.pattern_image,
            options=np.array([int(self.subpixel_mode.get()),
                              int(self.invert_output.get())]),
            mode=np.array([{'tile': 0, 'full': 1, 'image': 2}[self.mode]]),
            tile_dims=np.array([self.tile_n, self.tile_m]))
        self.status.config(text=f"Project saved: {os.path.basename(path)}")

    def _load_project(self):
        path = filedialog.askopenfilename(filetypes=[("Project", "*.npz")])
        if not path: return
        try:
            data = np.load(path)
            self.pattern_tile  = data['tile'].astype(np.uint8)
            self.pattern_full  = data['full'].astype(np.uint8)
            self.pattern_image = data['image'].astype(np.uint8)
            opts = data['options'].tolist()
            self.subpixel_mode.set(bool(opts[0]))
            self.invert_output.set(bool(opts[1]))
            mode_idx = int(data['mode'][0])
            self.mode = [MODE_TILE, MODE_FULL, MODE_IMAGE][mode_idx]
            # Tile dims (back-compat: old projects use 4x4)
            if 'tile_dims' in data.files:
                td = data['tile_dims'].tolist()
                self.tile_n = int(td[0]); self.tile_m = int(td[1])
            else:
                # Infer from the saved tile pattern shape
                th, tw = self.pattern_tile.shape
                if tw > 0 and th > 0 and LCD_WIDTH % tw == 0 and LCD_HEIGHT % th == 0:
                    self.tile_n = LCD_WIDTH  // tw
                    self.tile_m = LCD_HEIGHT // th
                else:
                    self.tile_n = DEFAULT_TILE_N
                    self.tile_m = DEFAULT_TILE_M
            # Clamp to known factors
            if self.tile_n not in HORIZ_DIVISIONS:
                self.tile_n = DEFAULT_TILE_N
            if self.tile_m not in VERT_DIVISIONS:
                self.tile_m = DEFAULT_TILE_M
            self.tile_n_var.set(self.tile_n)
            self.tile_m_var.set(self.tile_m)
        except Exception as ex:
            messagebox.showerror("Load failed", str(ex)); return
        # Reset histories with current state
        self.history = {MODE_TILE: [], MODE_FULL: [], MODE_IMAGE: []}
        self.hidx = {MODE_TILE: -1, MODE_FULL: -1, MODE_IMAGE: -1}
        for m in (MODE_TILE, MODE_FULL, MODE_IMAGE):
            self._snapshot(m)
        self._tile_cache = None
        self._update_tab_styles()
        self._build_toolbar()
        self._fit_to_canvas()
        self.status.config(text=f"Project loaded: {os.path.basename(path)}")


# ============================================================
if __name__ == "__main__":
    root = tk.Tk()
    MaskGenerator(root)
    root.mainloop()