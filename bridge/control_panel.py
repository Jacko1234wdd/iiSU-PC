"""
Unified control panel for iiSU-PC: one app for live status, Start/Stop with
a progress log, and a button into the config editor (config_editor.py).

Stdlib only (tkinter), no extra installs.
"""

import queue
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared import theme
from shared.theme import BG, GRAY, GREEN, PANEL_BG, RED, TEXT, TEXT_DIM, FONT_BODY, FONT_HEADING, FONT_MONO, FONT_TITLE, GRADIENT_STOPS, Card, QueueWriter, draw_gradient_bar

import start_iisu_pc
import stop_iisu_pc

SCRIPT_DIR = Path(__file__).parent

STATUS_POLL_INTERVAL_MS = 2000


class StatusDot(tk.Canvas):
    def __init__(self, parent, size=10):
        super().__init__(parent, width=size, height=size, bg=PANEL_BG, highlightthickness=0)
        self.size = size
        self.set_state("unknown")

    def set_state(self, state: str) -> None:
        color = {"up": GREEN, "down": RED, "unknown": GRAY}.get(state, GRAY)
        self.delete("all")
        pad = 1
        self.create_oval(pad, pad, self.size - pad, self.size - pad, fill=color, outline="")


class ControlPanel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("iiSU-PC")
        self.geometry("760x600")
        self.minsize(620, 480)
        self.configure(bg=BG)

        self.log_queue: queue.Queue = queue.Queue()
        self.busy = False

        self._configure_style()
        self._build_ui()
        self.after(100, self._poll_log_queue)
        self.after(200, self._poll_status)

    # -- Style -------------------------------------------------

    def _configure_style(self) -> None:
        theme.apply_ttk_styles(ttk.Style(self))

    # -- UI -------------------------------------------------

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=20, pady=(18, 8))
        tk.Label(header, text="iiSU-PC", font=FONT_TITLE, bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(header, text="Android frontend, real PC emulators.", font=FONT_BODY, bg=BG, fg=TEXT_DIM).pack(anchor="w")

        gradient = tk.Canvas(self, height=3, bg=BG, highlightthickness=0)
        gradient.pack(fill="x", padx=20, pady=(0, 14))
        self.after(10, lambda: draw_gradient_bar(gradient, gradient.winfo_width() or 720, 3))
        self.bind("<Configure>", lambda e: draw_gradient_bar(gradient, gradient.winfo_width(), 3))

        status_card = Card(self)
        status_card.pack(fill="x", padx=20, pady=(0, 12))
        status_inner = tk.Frame(status_card, bg=PANEL_BG)
        status_inner.pack(fill="x", padx=16, pady=14)

        self.avd_dot = StatusDot(status_inner)
        self.avd_dot.grid(row=0, column=0, padx=(0, 8))
        tk.Label(status_inner, text="Android VM", font=FONT_HEADING, bg=PANEL_BG, fg=TEXT).grid(row=0, column=1, sticky="w")
        self.avd_status_label = tk.Label(status_inner, text="checking...", font=FONT_BODY, bg=PANEL_BG, fg=TEXT_DIM)
        self.avd_status_label.grid(row=0, column=2, sticky="w", padx=(10, 0))

        self.bridge_dot = StatusDot(status_inner)
        self.bridge_dot.grid(row=1, column=0, padx=(0, 8), pady=(8, 0))
        tk.Label(status_inner, text="Launch bridge", font=FONT_HEADING, bg=PANEL_BG, fg=TEXT).grid(row=1, column=1, sticky="w", pady=(8, 0))
        self.bridge_status_label = tk.Label(status_inner, text="checking...", font=FONT_BODY, bg=PANEL_BG, fg=TEXT_DIM)
        self.bridge_status_label.grid(row=1, column=2, sticky="w", padx=(10, 0), pady=(8, 0))

        status_inner.grid_columnconfigure(2, weight=1)

        button_row = tk.Frame(self, bg=BG)
        button_row.pack(fill="x", padx=20, pady=(0, 12))
        self.start_button = ttk.Button(button_row, text="Start", style="Accent.TButton", command=self._start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(button_row, text="Stop", style="Accent.TButton", command=self._stop)
        self.stop_button.pack(side="left", padx=(10, 0))
        ttk.Button(button_row, text="Configure...", style="Ghost.TButton", command=self._open_configure).pack(side="left", padx=(10, 0))

        self.progress = ttk.Progressbar(button_row, mode="indeterminate", style="Dark.Horizontal.TProgressbar")
        self.progress.pack(side="left", fill="x", expand=True, padx=(16, 0))

        log_card = Card(self)
        log_card.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        log_inner = tk.Frame(log_card, bg=PANEL_BG)
        log_inner.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_text = tk.Text(log_inner, state="disabled", wrap="word", font=FONT_MONO, bg="#0e0e10", fg="#c9c9ce", insertbackground=TEXT, relief="flat", padx=8, pady=8)
        log_scroll = ttk.Scrollbar(log_inner, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    # -- Status polling -------------------------------------------------

    def _poll_status(self) -> None:
        threading.Thread(target=self._check_status, daemon=True).start()
        self.after(STATUS_POLL_INTERVAL_MS, self._poll_status)

    def _check_status(self) -> None:
        try:
            config = start_iisu_pc.load_config()
            avd_up = start_iisu_pc.is_avd_running(config["avd_name"])
            bridge_up = start_iisu_pc.is_port_open(config["bridge_port"])
        except Exception:
            avd_up = bridge_up = None
        self.after(0, self._apply_status, avd_up, bridge_up)

    def _apply_status(self, avd_up: bool | None, bridge_up: bool | None) -> None:
        if self.busy:
            return
        if avd_up is None:
            self.avd_dot.set_state("unknown")
            self.avd_status_label.config(text="unknown")
        else:
            self.avd_dot.set_state("up" if avd_up else "down")
            self.avd_status_label.config(text="running" if avd_up else "stopped")
        if bridge_up is None:
            self.bridge_dot.set_state("unknown")
            self.bridge_status_label.config(text="unknown")
        else:
            self.bridge_dot.set_state("up" if bridge_up else "down")
            self.bridge_status_label.config(text="running" if bridge_up else "stopped")

    # -- Log handling -------------------------------------------------

    def _append_log(self, text: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _poll_log_queue(self) -> None:
        try:
            while True:
                self._append_log(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    # -- Actions -------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.start_button.config(state=state)
        self.stop_button.config(state=state)
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def _start(self) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self._append_log("\n--- Start ---\n")
        threading.Thread(target=self._run_guarded, args=(start_iisu_pc.main,), daemon=True).start()

    def _stop(self) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self._append_log("\n--- Stop ---\n")
        threading.Thread(target=self._run_guarded, args=(stop_iisu_pc.main,), daemon=True).start()

    def _run_guarded(self, func) -> None:
        writer = QueueWriter(self.log_queue)
        old_stdout = sys.stdout
        sys.stdout = writer
        try:
            func()
        except SystemExit as e:
            if e.code not in (0, None):
                print(f"\n[panel] exited with code {e.code}\n")
        except Exception:
            print(f"\n[panel] error:\n{traceback.format_exc()}")
        finally:
            sys.stdout = old_stdout
        self.after(0, self._set_busy, False)

    def _open_configure(self) -> None:
        subprocess.Popen([sys.executable, "config_editor.py"], cwd=str(SCRIPT_DIR))


if __name__ == "__main__":
    ControlPanel().mainloop()
