"""
Standalone config editor for the iiSU launch bridge (config.json).

Lets you edit the ROM directory, emulator search folders, and the
package-name -> PC-emulator mappings without hand-editing JSON. The bridge
(launch_bridge.py) reloads config.json fresh on every launch request, so
changes saved here take effect on the very next game launch -- no need to
restart the bridge process.

Uses shared/theme.py so this and the other two front ends (control_panel.py,
installer/setup_gui.py) look like one application.

Stdlib only (tkinter), no extra installs.
"""

import json
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import winapi
from bridge_config import CONFIG_PATH, ConfigMissingError, load_config
from console_names import load_console_lookup, resolve_console_shortname

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared import theme
from shared.theme import BG, ENTRY_KWARGS, GRADIENT_STOPS, GREEN, LISTBOX_KWARGS, PANEL_BG, PANEL_BG_HOVER, RED, TEXT, TEXT_DIM, FONT_BODY, FONT_MONO, FONT_TITLE, QueueWriter, draw_gradient_bar
from shared.emulator_defaults import all_stub_packages, describe_profile

sys.path.insert(0, str(Path(__file__).parent.parent / "installer"))
import stub_apk

RESOLUTION_PRESETS = ["1280 x 720", "1600 x 900", "1920 x 1080", "2560 x 1440", "3840 x 2160"]
REFRESH_RATE_PRESETS = ["60", "90", "120", "144", "165", "240"]
MODIFIER_NAMES = ["ctrl", "alt", "shift", "win"]


def save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


class EmulatorDialog(simpledialog.Dialog):
    """Add/edit a single package-prefix -> emulator mapping."""

    def __init__(self, parent, title, prefix="", exe_names="", pre_args=""):
        self.initial_prefix = prefix
        self.initial_exe_names = exe_names
        self.initial_pre_args = pre_args
        self.result_values = None
        super().__init__(parent, title)

    def body(self, master):
        self.configure(bg=PANEL_BG)
        master.configure(bg=PANEL_BG)

        tk.Label(master, text="Android package prefix (e.g. com.github.stenzek.duckstation)", bg=PANEL_BG, fg=TEXT, font=FONT_BODY).grid(
            row=0, column=0, sticky="w", padx=4, pady=(4, 0)
        )
        self.prefix_entry = tk.Entry(master, width=50, **ENTRY_KWARGS)
        self.prefix_entry.insert(0, self.initial_prefix)
        self.prefix_entry.grid(row=1, column=0, padx=4, pady=(0, 8))

        tk.Label(master, text="Executable name(s), comma-separated (e.g. retroarch.exe)", bg=PANEL_BG, fg=TEXT, font=FONT_BODY).grid(
            row=2, column=0, sticky="w", padx=4
        )
        self.exe_entry = tk.Entry(master, width=50, **ENTRY_KWARGS)
        self.exe_entry.insert(0, self.initial_exe_names)
        self.exe_entry.grid(row=3, column=0, padx=4, pady=(0, 8))

        tk.Label(master, text="Launch flags, comma-separated (e.g. -fullscreen)", bg=PANEL_BG, fg=TEXT, font=FONT_BODY).grid(
            row=4, column=0, sticky="w", padx=4
        )
        self.args_entry = tk.Entry(master, width=50, **ENTRY_KWARGS)
        self.args_entry.insert(0, self.initial_pre_args)
        self.args_entry.grid(row=5, column=0, padx=4, pady=(0, 4))

        return self.prefix_entry

    def buttonbox(self):
        box = tk.Frame(self, bg=PANEL_BG)
        ttk.Button(box, text="OK", style="Accent.TButton", command=self.ok).pack(side="left", padx=5, pady=8)
        ttk.Button(box, text="Cancel", style="Ghost.TButton", command=self.cancel).pack(side="left", padx=5, pady=8)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        box.pack()

    def apply(self):
        prefix = self.prefix_entry.get().strip()
        exe_names = [s.strip() for s in self.exe_entry.get().split(",") if s.strip()]
        pre_args = [s.strip() for s in self.args_entry.get().split(",") if s.strip()]
        self.result_values = (prefix, exe_names, pre_args)


class RedirectorInstallDialog(tk.Toplevel):
    """Builds and installs a stub app for each of shared/emulator_defaults
    .py's known packages into the running AVD, so iiSU's own
    installed-package check resolves each console to something our
    patched LaunchBridge recognizes (see that module's docstring for why
    a stub is needed at all). The AVD needs to already be running --
    Start it from the control panel first if this can't reach it."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Install Redirector Apps")
        self.configure(bg=PANEL_BG)
        self.geometry("560x420")
        self.transient(parent)

        self.log_queue: queue.Queue = queue.Queue()
        self.running = False

        tk.Label(
            self, text="Installs a placeholder app for each of the emulators below into the\n"
            "running AVD, purely so iiSU recognizes that console's emulator as\n"
            "installed. The real launch is still handled by the PC-side emulator\n"
            "configured in the Emulators tab -- these apps do nothing themselves.",
            bg=PANEL_BG, fg=TEXT_DIM, font=FONT_BODY, justify="left",
        ).pack(anchor="w", padx=16, pady=(16, 8))

        self.replace_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self, text="Replace apps already installed under these package names\n(only do this if you're sure it's an old redirector, not a real app)",
            variable=self.replace_var,
        ).pack(anchor="w", padx=16, pady=(0, 8))

        self.log_text = tk.Text(self, state="disabled", wrap="word", font=FONT_MONO, bg="#0e0e10", fg="#c9c9ce", relief="flat", padx=8, pady=8, height=12)
        self.log_text.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        button_row = tk.Frame(self, bg=PANEL_BG)
        button_row.pack(fill="x", padx=16, pady=(0, 16))
        self.install_button = ttk.Button(button_row, text="Install All", style="Accent.TButton", command=self._start_install)
        self.install_button.pack(side="left")
        ttk.Button(button_row, text="Close", style="Ghost.TButton", command=self.destroy).pack(side="left", padx=(8, 0))

        self.after(100, self._poll_log_queue)

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

    def _start_install(self) -> None:
        if self.running:
            return
        self.running = True
        self.install_button.config(state="disabled")
        threading.Thread(target=self._run_installs, args=(self.replace_var.get(),), daemon=True).start()

    def _run_installs(self, replace_existing: bool) -> None:
        writer = QueueWriter(self.log_queue)
        devices = subprocess.run(["adb", "devices"], capture_output=True, text=True)
        if not any(line.startswith("emulator-") and "device" in line for line in devices.stdout.splitlines()):
            writer.write("No running AVD found -- start it from the control panel first, then try again.\n")
            self.after(0, self._on_finished)
            return

        for package, label in all_stub_packages():
            writer.write(f"{label} ({package})... ")
            try:
                outcome = stub_apk.build_and_install(package, label, replace_existing=replace_existing)
                writer.write(f"{outcome}\n")
            except Exception as e:
                writer.write(f"failed ({e})\n")
        writer.write("\nDone.\n")
        self.after(0, self._on_finished)

    def _on_finished(self) -> None:
        self.running = False
        self.install_button.config(state="normal")


class SetupApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("iiSU-PC Configure")
        self.geometry("760x760")
        self.minsize(680, 640)
        self.configure(bg=BG)

        try:
            self.config_data = load_config()
        except ConfigMissingError as e:
            self.withdraw()
            messagebox.showerror("Config not found", str(e))
            sys.exit(1)

        self._configure_style()
        self._build_header()

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        self.roms_tab = tk.Frame(notebook, bg=PANEL_BG)
        self.emulators_tab = tk.Frame(notebook, bg=PANEL_BG)
        self.display_tab = tk.Frame(notebook, bg=PANEL_BG)
        self.advanced_tab = tk.Frame(notebook, bg=PANEL_BG)
        notebook.add(self.roms_tab, text="ROM Directory")
        notebook.add(self.emulators_tab, text="Emulators")
        notebook.add(self.display_tab, text="Display")
        notebook.add(self.advanced_tab, text="Advanced")

        self._build_roms_tab()
        self._build_emulators_tab()
        self._build_display_tab()
        self._build_advanced_tab()

        save_bar = tk.Frame(self, bg=BG)
        save_bar.pack(fill="x", padx=20, pady=(0, 18))
        ttk.Button(save_bar, text="Save", style="Accent.TButton", command=self.save).pack(side="right")
        self.status_label = tk.Label(save_bar, text="", bg=BG, fg=GREEN, font=FONT_BODY)
        self.status_label.pack(side="left")

    # -- Style / header -------------------------------------------------

    def _configure_style(self) -> None:
        theme.apply_ttk_styles(ttk.Style(self))

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=20, pady=(18, 8))
        tk.Label(header, text="iiSU-PC Configure", font=FONT_TITLE, bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(header, text="ROM directory, emulator mappings, display, and hotkeys.", font=FONT_BODY, bg=BG, fg=TEXT_DIM).pack(anchor="w")

        gradient = tk.Canvas(self, height=3, bg=BG, highlightthickness=0)
        gradient.pack(fill="x", padx=20, pady=(10, 14))
        self.after(10, lambda: draw_gradient_bar(gradient, gradient.winfo_width() or 700, 3))
        self.bind("<Configure>", lambda e: draw_gradient_bar(gradient, gradient.winfo_width(), 3))

    # -- ROM directory tab -------------------------------------------------

    def _build_roms_tab(self):
        frame = self.roms_tab
        tk.Label(frame, text="Root ROM folder (contains one subfolder per console):", bg=PANEL_BG, fg=TEXT, font=FONT_BODY).pack(
            anchor="w", padx=16, pady=(16, 0)
        )
        row = tk.Frame(frame, bg=PANEL_BG)
        row.pack(fill="x", padx=16, pady=4)
        self.roms_dir_var = tk.StringVar(value=self.config_data.get("roms_dir", ""))
        roms_entry = tk.Entry(row, textvariable=self.roms_dir_var, **ENTRY_KWARGS)
        roms_entry.pack(side="left", fill="x", expand=True, ipady=3)
        roms_entry.bind("<FocusOut>", lambda e: self._refresh_roms_status())
        ttk.Button(row, text="Browse...", style="Ghost.TButton", command=self._browse_roms_dir).pack(side="left", padx=(8, 0))

        # Live feedback on whether iiSU will actually recognize what's in
        # there, instead of only finding out after saving and rescanning.
        self.roms_status_label = tk.Label(frame, text="", bg=PANEL_BG, font=FONT_BODY, justify="left", wraplength=620, anchor="w")
        self.roms_status_label.pack(anchor="w", fill="x", padx=16, pady=(6, 0))
        self._refresh_roms_status()

        tk.Label(frame, text="Folders to search for emulator executables:", bg=PANEL_BG, fg=TEXT, font=FONT_BODY).pack(
            anchor="w", padx=16, pady=(16, 0)
        )
        self.search_roots_list = tk.Listbox(frame, height=6, font=FONT_BODY, **LISTBOX_KWARGS)
        self.search_roots_list.pack(fill="both", expand=True, padx=16, pady=6)
        for root in self.config_data.get("search_roots", []):
            self.search_roots_list.insert("end", root)

        btn_row = tk.Frame(frame, bg=PANEL_BG)
        btn_row.pack(fill="x", padx=16, pady=(0, 16))
        ttk.Button(btn_row, text="Add folder...", style="Ghost.TButton", command=self._add_search_root).pack(side="left")
        ttk.Button(btn_row, text="Remove selected", style="Ghost.TButton", command=self._remove_search_root).pack(
            side="left", padx=(8, 0)
        )

    def _refresh_roms_status(self) -> None:
        raw = self.roms_dir_var.get().strip()
        if not raw:
            self.roms_status_label.config(text="", fg=TEXT_DIM)
            return
        path = Path(raw)
        if not path.is_dir():
            self.roms_status_label.config(text="✗ This folder doesn't exist yet.", fg=RED)
            return

        exact, by_compact = load_console_lookup()
        recognized, unrecognized = [], []
        for child in sorted(path.iterdir()):
            if not child.is_dir():
                continue
            (recognized if resolve_console_shortname(child.name, exact, by_compact) else unrecognized).append(child.name)

        if not recognized and not unrecognized:
            self.roms_status_label.config(text="This folder is empty.", fg=TEXT_DIM)
        elif not unrecognized:
            self.roms_status_label.config(
                text=f"✓ iiSU will recognize all {len(recognized)} folder(s): {', '.join(recognized)}", fg=GREEN
            )
        else:
            prefix = f"✓ {len(recognized)} recognized, " if recognized else ""
            self.roms_status_label.config(
                text=f"{prefix}✗ {len(unrecognized)} won't be seen by iiSU (rename these): {', '.join(unrecognized)}",
                fg=RED,
            )

    def _browse_roms_dir(self):
        path = filedialog.askdirectory(title="Select root ROM folder")
        if path:
            self.roms_dir_var.set(path)
            self._refresh_roms_status()

    def _add_search_root(self):
        path = filedialog.askdirectory(title="Select a folder to search for emulators")
        if path:
            self.search_roots_list.insert("end", path)

    def _remove_search_root(self):
        for index in reversed(self.search_roots_list.curselection()):
            self.search_roots_list.delete(index)

    # -- Emulators tab -------------------------------------------------

    def _build_emulators_tab(self):
        frame = self.emulators_tab
        tk.Label(
            frame,
            text="Maps the Android package name iiSU tries to launch to a real PC emulator.",
            bg=PANEL_BG, fg=TEXT, font=FONT_BODY,
        ).pack(anchor="w", padx=16, pady=(16, 6))

        columns = ("prefix", "exe_names", "pre_args")
        self.emulators_tree = ttk.Treeview(frame, columns=columns, show="headings", height=12)
        self.emulators_tree.heading("prefix", text="Package prefix")
        self.emulators_tree.heading("exe_names", text="Executable name(s)")
        self.emulators_tree.heading("pre_args", text="Launch flags")
        self.emulators_tree.column("prefix", width=220)
        self.emulators_tree.column("exe_names", width=200)
        self.emulators_tree.column("pre_args", width=150)
        self.emulators_tree.pack(fill="both", expand=True, padx=16, pady=4)

        for prefix, profile in self.config_data.get("emulators", {}).items():
            exe_display, pre_args_display = describe_profile(profile)
            self.emulators_tree.insert("", "end", iid=prefix, values=(prefix, exe_display, pre_args_display))

        btn_row = tk.Frame(frame, bg=PANEL_BG)
        btn_row.pack(fill="x", padx=16, pady=(0, 16))
        ttk.Button(btn_row, text="Add...", style="Ghost.TButton", command=self._add_emulator).pack(side="left")
        ttk.Button(btn_row, text="Edit selected...", style="Ghost.TButton", command=self._edit_emulator).pack(side="left", padx=(8, 0))
        ttk.Button(btn_row, text="Remove selected", style="Ghost.TButton", command=self._remove_emulator).pack(side="left", padx=(8, 0))
        ttk.Button(btn_row, text="Install Redirector Apps...", style="Ghost.TButton", command=self._open_redirector_dialog).pack(side="left", padx=(8, 0))

    def _open_redirector_dialog(self) -> None:
        RedirectorInstallDialog(self)

    def _add_emulator(self):
        dialog = EmulatorDialog(self, "Add emulator mapping")
        if dialog.result_values:
            prefix, exe_names, pre_args = dialog.result_values
            if not prefix:
                return
            if self.emulators_tree.exists(prefix):
                messagebox.showerror("Duplicate", f"A mapping for '{prefix}' already exists.")
                return
            self.emulators_tree.insert(
                "", "end", iid=prefix, values=(prefix, ", ".join(exe_names), ", ".join(pre_args))
            )

    def _edit_emulator(self):
        selected = self.emulators_tree.selection()
        if not selected:
            return
        prefix = selected[0]
        if "by_extension" in self.config_data.get("emulators", {}).get(prefix, {}):
            messagebox.showinfo(
                "Can't edit here",
                "This entry maps a different executable per ROM file extension "
                "(see shared/emulator_defaults.py) -- editing it as one flat "
                "executable/flags pair isn't supported here. Edit config.json "
                "directly if you need to change it.",
            )
            return
        values = self.emulators_tree.item(prefix, "values")
        dialog = EmulatorDialog(
            self, "Edit emulator mapping", prefix=values[0], exe_names=values[1], pre_args=values[2]
        )
        if dialog.result_values:
            new_prefix, exe_names, pre_args = dialog.result_values
            self.emulators_tree.delete(prefix)
            self.emulators_tree.insert(
                "", "end", iid=new_prefix, values=(new_prefix, ", ".join(exe_names), ", ".join(pre_args))
            )

    def _remove_emulator(self):
        for item in self.emulators_tree.selection():
            self.emulators_tree.delete(item)

    # -- Display tab -------------------------------------------------

    def _build_display_tab(self):
        frame = self.display_tab
        frame.grid_columnconfigure(0, weight=1)

        tk.Label(
            frame,
            text="iiSU's default AVD profile is a portrait phone screen, which\n"
            "looks cramped on a desktop. These settings change the emulated\n"
            "device's actual hardware profile (not a runtime overlay), so\n"
            "there's no letterboxing -- but applying them cold-boots the AVD.",
            bg=PANEL_BG, fg=TEXT_DIM, font=FONT_BODY,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(16, 12))

        display = self.config_data.get(
            "display", {"width": 1920, "height": 1080, "density": 240, "refresh_rate": 60}
        )
        self.display_width_var = tk.StringVar(value=str(display.get("width", 1920)))
        self.display_height_var = tk.StringVar(value=str(display.get("height", 1080)))
        self.display_density_var = tk.StringVar(value=str(display.get("density", 240)))
        self.display_refresh_var = tk.StringVar(value=str(display.get("refresh_rate", 60)))

        settings_col = tk.Frame(frame, bg=PANEL_BG)
        settings_col.grid(row=1, column=0, sticky="nw", padx=16)

        tk.Label(settings_col, text="Resolution:", bg=PANEL_BG, fg=TEXT, font=FONT_BODY).grid(row=0, column=0, sticky="w")
        self.resolution_preset_var = tk.StringVar()
        resolution_combo = ttk.Combobox(
            settings_col, textvariable=self.resolution_preset_var, values=RESOLUTION_PRESETS,
            state="readonly", width=14, font=FONT_BODY,
        )
        resolution_combo.grid(row=0, column=1, sticky="w", padx=(8, 4), pady=3)
        resolution_combo.bind("<<ComboboxSelected>>", self._apply_resolution_preset)

        tk.Label(settings_col, text="or exactly:", bg=PANEL_BG, fg=TEXT_DIM, font=FONT_BODY).grid(row=1, column=0, sticky="w", pady=3)
        exact_row = tk.Frame(settings_col, bg=PANEL_BG)
        exact_row.grid(row=1, column=1, sticky="w", padx=(8, 0))
        width_entry = tk.Entry(exact_row, textvariable=self.display_width_var, width=6, **ENTRY_KWARGS)
        width_entry.pack(side="left")
        tk.Label(exact_row, text="x", bg=PANEL_BG, fg=TEXT_DIM, font=FONT_BODY).pack(side="left", padx=4)
        height_entry = tk.Entry(exact_row, textvariable=self.display_height_var, width=6, **ENTRY_KWARGS)
        height_entry.pack(side="left")

        tk.Label(settings_col, text="Density (dpi):", bg=PANEL_BG, fg=TEXT, font=FONT_BODY).grid(row=2, column=0, sticky="w", pady=3)
        tk.Entry(settings_col, textvariable=self.display_density_var, width=8, **ENTRY_KWARGS).grid(
            row=2, column=1, sticky="w", padx=(8, 0), pady=3
        )

        tk.Label(settings_col, text="Refresh rate (Hz):", bg=PANEL_BG, fg=TEXT, font=FONT_BODY).grid(row=3, column=0, sticky="w", pady=3)
        refresh_row = tk.Frame(settings_col, bg=PANEL_BG)
        refresh_row.grid(row=3, column=1, sticky="w", padx=(8, 0))
        tk.Entry(refresh_row, textvariable=self.display_refresh_var, width=6, **ENTRY_KWARGS).pack(side="left")
        refresh_combo = ttk.Combobox(refresh_row, values=REFRESH_RATE_PRESETS, state="readonly", width=5, font=FONT_BODY)
        refresh_combo.pack(side="left", padx=(6, 0))
        refresh_combo.bind("<<ComboboxSelected>>", lambda e: self.display_refresh_var.set(refresh_combo.get()))

        # A live preview beats squinting at four numbers to picture the shape.
        preview_col = tk.Frame(frame, bg=PANEL_BG)
        preview_col.grid(row=1, column=1, sticky="ne", padx=16)
        tk.Label(preview_col, text="Preview", bg=PANEL_BG, fg=TEXT_DIM, font=FONT_BODY).pack(anchor="e")
        self.aspect_canvas = tk.Canvas(preview_col, width=150, height=100, bg="#0e0e10", highlightthickness=0)
        self.aspect_canvas.pack()
        self.display_width_var.trace_add("write", self._redraw_aspect_preview)
        self.display_height_var.trace_add("write", self._redraw_aspect_preview)
        self._redraw_aspect_preview()

        tk.Label(
            frame,
            text="Only affects iiSU's own UI smoothness inside the AVD -- actual\n"
            "gameplay runs in a separate native Windows emulator process, which\n"
            "already uses your monitor's real refresh rate with no setup needed.",
            bg=PANEL_BG, fg=TEXT_DIM, font=FONT_BODY,
            justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=16, pady=(10, 8))

        ttk.Button(
            frame, text="Auto-detect from primary monitor", style="Ghost.TButton", command=self._autodetect_display
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=16, pady=(4, 0))

        self.iisu_fullscreen_var = tk.BooleanVar(value=self.config_data.get("iisu_fullscreen", True))
        ttk.Checkbutton(
            frame, text="Maximize the iiSU/AVD window automatically", variable=self.iisu_fullscreen_var
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=16, pady=(12, 0))

        tk.Label(frame, text="AVD name:", bg=PANEL_BG, fg=TEXT, font=FONT_BODY).grid(row=5, column=0, sticky="w", padx=16, pady=(16, 0))
        self.avd_name_var = tk.StringVar(value=self.config_data.get("avd_name", "medium_phone"))
        tk.Entry(frame, textvariable=self.avd_name_var, width=20, **ENTRY_KWARGS).grid(
            row=6, column=0, sticky="w", padx=16, pady=(4, 8)
        )

        ttk.Button(
            frame, text="Apply now (saves + cold-boots the AVD)", style="Accent.TButton", command=self._apply_display
        ).grid(row=7, column=0, columnspan=2, sticky="w", padx=16, pady=(8, 0))
        self.display_status_label = tk.Label(frame, text="", bg=PANEL_BG, fg=GRADIENT_STOPS[2], font=FONT_BODY)
        self.display_status_label.grid(row=8, column=0, columnspan=2, sticky="w", padx=16, pady=(8, 16))

    def _apply_resolution_preset(self, event=None) -> None:
        choice = self.resolution_preset_var.get()
        if "x" not in choice:
            return
        width, height = (part.strip() for part in choice.split("x"))
        self.display_width_var.set(width)
        self.display_height_var.set(height)

    def _redraw_aspect_preview(self, *_args) -> None:
        canvas = self.aspect_canvas
        canvas.delete("all")
        box_w, box_h = int(canvas["width"]), int(canvas["height"])
        try:
            width = int(self.display_width_var.get())
            height = int(self.display_height_var.get())
        except ValueError:
            return
        if width <= 0 or height <= 0:
            return
        margin = 10
        scale = min((box_w - margin * 2) / width, (box_h - margin * 2) / height)
        rect_w, rect_h = width * scale, height * scale
        x0, y0 = (box_w - rect_w) / 2, (box_h - rect_h) / 2
        canvas.create_rectangle(x0, y0, x0 + rect_w, y0 + rect_h, fill=PANEL_BG_HOVER, outline=GRADIENT_STOPS[2], width=2)
        canvas.create_text(box_w / 2, box_h / 2, text=f"{width}×{height}", fill=TEXT, font=FONT_BODY)

    def _autodetect_display(self):
        width, height, hz = winapi.get_primary_monitor_mode()
        self.display_width_var.set(str(width))
        self.display_height_var.set(str(height))
        self.display_refresh_var.set(str(hz))

    def _apply_display(self):
        self.save()
        self.display_status_label.config(text="Cold-booting the AVD, this takes a minute...")
        self.update_idletasks()
        subprocess.Popen(
            [sys.executable, str(Path(__file__).parent / "apply_display.py")],
        )

    # -- Advanced tab -------------------------------------------------

    def _build_advanced_tab(self):
        frame = self.advanced_tab

        tk.Label(frame, text="iiSU window title match:", bg=PANEL_BG, fg=TEXT, font=FONT_BODY).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 0))
        self.window_title_var = tk.StringVar(value=self.config_data.get("iisu_window_title", ""))
        tk.Entry(frame, textvariable=self.window_title_var, width=40, **ENTRY_KWARGS).grid(
            row=1, column=0, sticky="w", padx=16, pady=(4, 8)
        )

        tk.Label(frame, text="Bridge listen port:", bg=PANEL_BG, fg=TEXT, font=FONT_BODY).grid(row=2, column=0, sticky="w", padx=16)
        self.port_var = tk.StringVar(value=str(self.config_data.get("bridge_port", 7737)))
        tk.Entry(frame, textvariable=self.port_var, width=10, **ENTRY_KWARGS).grid(row=3, column=0, sticky="w", padx=16, pady=(4, 8))

        self.quit_hotkey_vars = self._build_hotkey_editor(
            frame, row=4, title="Quit-to-frontend hotkey (force-quits the running emulator, returns to iiSU):",
            initial=self.config_data.get("quit_hotkey", {"modifiers": ["ctrl", "alt"], "key": "q"}),
        )
        self.shutdown_hotkey_vars = self._build_hotkey_editor(
            frame, row=7, title="Full-shutdown hotkey (closes iiSU and the AVD entirely):",
            initial=self.config_data.get("shutdown_hotkey", {"modifiers": ["ctrl", "alt"], "key": "x"}),
        )

        tk.Label(
            frame,
            text="Port and hotkey changes need the bridge restarted to take effect\n"
            "(ROM directory, search folders, and emulator mappings apply on\n"
            "the very next game launch, no restart needed).",
            bg=PANEL_BG, fg=TEXT_DIM, font=FONT_BODY,
            justify="left",
        ).grid(row=10, column=0, sticky="w", padx=16, pady=(8, 16))

    def _build_hotkey_editor(self, parent, row: int, title: str, initial: dict) -> dict:
        """Builds one hotkey's editor -- a checkbox per modifier plus a
        "press a key" capture button instead of free-typed text -- and
        returns the tk variables backing it, read back in save()."""
        tk.Label(parent, text=title, bg=PANEL_BG, fg=TEXT, font=FONT_BODY).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=16, pady=(4, 2)
        )

        initial_mods = {m.lower() for m in initial.get("modifiers", [])}
        mod_row = tk.Frame(parent, bg=PANEL_BG)
        mod_row.grid(row=row + 1, column=0, columnspan=2, sticky="w", padx=16)
        mod_vars = {}
        for name in MODIFIER_NAMES:
            var = tk.BooleanVar(value=name in initial_mods)
            mod_vars[name] = var
            ttk.Checkbutton(mod_row, text=name.capitalize(), variable=var).pack(side="left", padx=(0, 12))

        key_row = tk.Frame(parent, bg=PANEL_BG)
        key_row.grid(row=row + 2, column=0, columnspan=2, sticky="w", padx=16, pady=(4, 8))
        tk.Label(key_row, text="+", bg=PANEL_BG, fg=TEXT_DIM, font=FONT_BODY).pack(side="left", padx=(0, 8))
        key_var = tk.StringVar(value=initial.get("key", ""))
        key_display = tk.Label(key_row, textvariable=key_var, width=8, bg="#0e0e10", fg=TEXT, font=FONT_BODY, relief="flat", padx=8, pady=4)
        key_display.pack(side="left")
        capture_button = ttk.Button(key_row, text="Press a key...", style="Ghost.TButton")
        capture_button.configure(command=lambda: self._capture_key(key_var, capture_button))
        capture_button.pack(side="left", padx=(8, 0))

        return {"mods": mod_vars, "key": key_var}

    def _capture_key(self, key_var: tk.StringVar, button: ttk.Button) -> None:
        original_text = button.cget("text")
        button.configure(text="press any key...", state="disabled")

        def on_key(event: tk.Event) -> None:
            self.unbind("<KeyPress>")
            # keysym is unreliable for some synthetic/IME input (comes back
            # as the literal string "??"); event.char still has the actual
            # character in that case, so fall back to it.
            keysym = event.keysym if event.keysym not in ("??", "") else event.char
            if keysym:
                key_var.set(keysym.lower())
            button.configure(text=original_text, state="normal")

        self.bind("<KeyPress>", on_key)

    # -- Save -------------------------------------------------

    @staticmethod
    def _read_hotkey(hotkey_vars: dict, default_key: str) -> dict:
        return {
            "modifiers": [name for name, var in hotkey_vars["mods"].items() if var.get()],
            "key": hotkey_vars["key"].get().strip() or default_key,
        }

    def save(self):
        original_emulators = self.config_data.get("emulators", {})
        emulators = {}
        for item in self.emulators_tree.get_children():
            prefix, exe_names_str, pre_args_str = self.emulators_tree.item(item, "values")
            # "by_extension" entries (e.g. com.retroarch, which maps to a
            # different real PC emulator per ROM extension rather than one
            # fixed exe) show a human-readable summary in these columns (see
            # describe_profile), not the real underlying data -- always keep
            # the original entry verbatim rather than reconstructing it from
            # that summary text. _edit_emulator() already refuses to open on
            # these, so the only way one changes at all is via Remove.
            original = original_emulators.get(prefix, {})
            if "by_extension" in original:
                emulators[prefix] = original
                continue
            emulators[prefix] = {
                "exe_names": [s.strip() for s in exe_names_str.split(",") if s.strip()],
                "pre_args": [s.strip() for s in pre_args_str.split(",") if s.strip()],
            }

        try:
            port = int(self.port_var.get())
        except ValueError:
            messagebox.showerror("Invalid port", "Bridge listen port must be a number.")
            return

        try:
            display = {
                "width": int(self.display_width_var.get()),
                "height": int(self.display_height_var.get()),
                "density": int(self.display_density_var.get()),
                "refresh_rate": int(self.display_refresh_var.get()),
            }
        except ValueError:
            messagebox.showerror(
                "Invalid display settings", "Width, height, density, and refresh rate must be numbers."
            )
            return

        self.config_data = {
            "bridge_port": port,
            "roms_dir": self.roms_dir_var.get().strip(),
            "search_roots": list(self.search_roots_list.get(0, "end")),
            "iisu_window_title": self.window_title_var.get().strip(),
            "iisu_fullscreen": self.iisu_fullscreen_var.get(),
            "iisu_component": self.config_data.get(
                "iisu_component", "com.iisulauncher/com.iisulauncher.launcher.StartupSafeModeActivity"
            ),
            "avd_name": self.avd_name_var.get().strip() or "medium_phone",
            "display": display,
            "quit_hotkey": self._read_hotkey(self.quit_hotkey_vars, default_key="q"),
            "shutdown_hotkey": self._read_hotkey(self.shutdown_hotkey_vars, default_key="x"),
            "emulators": emulators,
        }

        save_config(self.config_data)
        self.status_label.config(text=f"Saved to {CONFIG_PATH.name}")
        self.after(3000, lambda: self.status_label.config(text=""))


if __name__ == "__main__":
    SetupApp().mainloop()
