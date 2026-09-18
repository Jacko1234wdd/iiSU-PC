"""
Shared dark-UI theme for iiSU-PC's tkinter front ends (bridge/control_panel.py,
installer/setup_gui.py): one palette, font set, and small set of building
blocks so both windows read as one application instead of two unrelated
tools bolted together.

The palette echoes iiSU's own in-app look (dark background, tile-style
panels, its cyan-to-purple gradient) -- colors and layout only, not any of
iiSU's actual asset files (fonts, icons), since those are iiSU's own
copyrighted assets and not ours to include.
"""

import queue
import tkinter as tk
from tkinter import ttk

BG = "#141414"
PANEL_BG = "#212124"
PANEL_BG_HOVER = "#2a2a2e"
TEXT = "#f2f2f4"
TEXT_DIM = "#9a9aa2"
GRADIENT_STOPS = ["#71e0ff", "#68ccff", "#5e84ff", "#8258fa", "#c56eff"]
GREEN = "#4fd67a"
RED = "#ff6161"
GRAY = "#5a5a60"

FONT_TITLE = ("Segoe UI Semibold", 20)
FONT_HEADING = ("Segoe UI Semibold", 11)
FONT_BODY = ("Segoe UI", 10)
FONT_MONO = ("Consolas", 9)


class QueueWriter:
    """A writable stream that pushes text into a queue instead of a real
    file, so a background thread's plain print() calls can reach a tkinter
    log widget without the printing code needing to know a GUI exists."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, text: str) -> None:
        if text:
            self.q.put(text)

    def flush(self) -> None:
        pass


def draw_gradient_bar(canvas: tk.Canvas, width: int, height: int) -> None:
    """Horizontal multi-stop gradient, drawn as a strip of thin rectangles
    since tkinter has no native gradient fill."""
    canvas.delete("all")
    steps = max(width, 1)
    n_stops = len(GRADIENT_STOPS)
    stop_rgbs = [canvas.winfo_rgb(c) for c in GRADIENT_STOPS]
    for x in range(steps):
        t = x / max(steps - 1, 1) * (n_stops - 1)
        i = min(int(t), n_stops - 2)
        frac = t - i
        r1, g1, b1 = stop_rgbs[i]
        r2, g2, b2 = stop_rgbs[i + 1]
        r = int(r1 + (r2 - r1) * frac) >> 8
        g = int(g1 + (g2 - g1) * frac) >> 8
        b = int(b1 + (b2 - b1) * frac) >> 8
        canvas.create_line(x, 0, x, height, fill=f"#{r:02x}{g:02x}{b:02x}")


class Card(tk.Frame):
    """A rounded-ish dark panel echoing iiSU's tile style. tkinter has no
    native rounded-rect widget background, so this approximates it with a
    plain dark panel and generous padding rather than fighting the toolkit
    for pixel-perfect corners."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=PANEL_BG, highlightthickness=0, **kwargs)


def apply_ttk_styles(style: ttk.Style) -> None:
    """Configures the ttk styles both front ends build their buttons and
    progress bar from (Accent.TButton, Ghost.TButton,
    Dark.Horizontal.TProgressbar), so a style tweak only has to happen in
    one place."""
    style.theme_use("clam")
    style.configure("Accent.TButton", background="#3a3a40", foreground=TEXT, font=FONT_HEADING, padding=(16, 10), borderwidth=0)
    style.map("Accent.TButton", background=[("active", "#48484f"), ("disabled", "#2a2a2e")], foreground=[("disabled", TEXT_DIM)])
    style.configure("Ghost.TButton", background=PANEL_BG, foreground=TEXT, font=FONT_BODY, padding=(12, 6), borderwidth=0)
    style.map("Ghost.TButton", background=[("active", PANEL_BG_HOVER)])
    style.configure("Dark.Horizontal.TProgressbar", background=GRADIENT_STOPS[2], troughcolor=PANEL_BG, borderwidth=0)
