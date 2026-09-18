"""
Standalone config editor for the iiSU launch bridge (config.json).

Lets you edit the ROM directory, emulator search folders, and the
package-name -> PC-emulator mappings without hand-editing JSON. The bridge
(launch_bridge.py) reloads config.json fresh on every launch request, so
changes saved here take effect on the very next game launch -- no need to
restart the bridge process.

Stdlib only (tkinter), no extra installs.
"""

import json
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import winapi

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


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
        tk.Label(master, text="Android package prefix (e.g. com.github.stenzek.duckstation)").grid(
            row=0, column=0, sticky="w", padx=4, pady=(4, 0)
        )
        self.prefix_entry = tk.Entry(master, width=50)
        self.prefix_entry.insert(0, self.initial_prefix)
        self.prefix_entry.grid(row=1, column=0, padx=4, pady=(0, 8))

        tk.Label(master, text="Executable name(s), comma-separated (e.g. retroarch.exe)").grid(
            row=2, column=0, sticky="w", padx=4
        )
        self.exe_entry = tk.Entry(master, width=50)
        self.exe_entry.insert(0, self.initial_exe_names)
        self.exe_entry.grid(row=3, column=0, padx=4, pady=(0, 8))

        tk.Label(master, text="Launch flags, comma-separated (e.g. -fullscreen)").grid(
            row=4, column=0, sticky="w", padx=4
        )
        self.args_entry = tk.Entry(master, width=50)
        self.args_entry.insert(0, self.initial_pre_args)
        self.args_entry.grid(row=5, column=0, padx=4, pady=(0, 4))

        return self.prefix_entry

    def apply(self):
        prefix = self.prefix_entry.get().strip()
        exe_names = [s.strip() for s in self.exe_entry.get().split(",") if s.strip()]
        pre_args = [s.strip() for s in self.args_entry.get().split(",") if s.strip()]
        self.result_values = (prefix, exe_names, pre_args)


class SetupApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("iiSU-PC Bridge Setup")
        self.geometry("640x560")

        self.config_data = load_config()

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.roms_tab = ttk.Frame(notebook)
        self.emulators_tab = ttk.Frame(notebook)
        self.display_tab = ttk.Frame(notebook)
        self.advanced_tab = ttk.Frame(notebook)
        notebook.add(self.roms_tab, text="ROM Directory")
        notebook.add(self.emulators_tab, text="Emulators")
        notebook.add(self.display_tab, text="Display")
        notebook.add(self.advanced_tab, text="Advanced")

        self._build_roms_tab()
        self._build_emulators_tab()
        self._build_display_tab()
        self._build_advanced_tab()

        save_bar = tk.Frame(self)
        save_bar.pack(fill="x", padx=8, pady=(0, 8))
        tk.Button(save_bar, text="Save", command=self.save, width=12).pack(side="right")
        self.status_label = tk.Label(save_bar, text="", fg="green")
        self.status_label.pack(side="left")

    # -- ROM directory tab -------------------------------------------------

    def _build_roms_tab(self):
        frame = self.roms_tab
        tk.Label(frame, text="Root ROM folder (contains one subfolder per console):").pack(
            anchor="w", padx=8, pady=(12, 0)
        )
        row = tk.Frame(frame)
        row.pack(fill="x", padx=8, pady=4)
        self.roms_dir_var = tk.StringVar(value=self.config_data.get("roms_dir", ""))
        tk.Entry(row, textvariable=self.roms_dir_var).pack(side="left", fill="x", expand=True)
        tk.Button(row, text="Browse...", command=self._browse_roms_dir).pack(side="left", padx=(4, 0))

        tk.Label(
            frame,
            text="Each subfolder's name must match one of iiSU's known console\n"
            "short/long names (e.g. \"psx\", \"n64\") or iiSU will reject it.",
            fg="gray",
            justify="left",
        ).pack(anchor="w", padx=8, pady=(4, 0))

        tk.Label(frame, text="Folders to search for emulator executables:").pack(
            anchor="w", padx=8, pady=(16, 0)
        )
        self.search_roots_list = tk.Listbox(frame, height=6)
        self.search_roots_list.pack(fill="both", expand=True, padx=8, pady=4)
        for root in self.config_data.get("search_roots", []):
            self.search_roots_list.insert("end", root)

        btn_row = tk.Frame(frame)
        btn_row.pack(fill="x", padx=8)
        tk.Button(btn_row, text="Add folder...", command=self._add_search_root).pack(side="left")
        tk.Button(btn_row, text="Remove selected", command=self._remove_search_root).pack(
            side="left", padx=(4, 0)
        )

    def _browse_roms_dir(self):
        path = filedialog.askdirectory(title="Select root ROM folder")
        if path:
            self.roms_dir_var.set(path)

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
        ).pack(anchor="w", padx=8, pady=(12, 4))

        columns = ("prefix", "exe_names", "pre_args")
        self.emulators_tree = ttk.Treeview(frame, columns=columns, show="headings", height=12)
        self.emulators_tree.heading("prefix", text="Package prefix")
        self.emulators_tree.heading("exe_names", text="Executable name(s)")
        self.emulators_tree.heading("pre_args", text="Launch flags")
        self.emulators_tree.column("prefix", width=220)
        self.emulators_tree.column("exe_names", width=200)
        self.emulators_tree.column("pre_args", width=150)
        self.emulators_tree.pack(fill="both", expand=True, padx=8, pady=4)

        for prefix, profile in self.config_data.get("emulators", {}).items():
            self.emulators_tree.insert(
                "",
                "end",
                iid=prefix,
                values=(prefix, ", ".join(profile.get("exe_names", [])), ", ".join(profile.get("pre_args", []))),
            )

        btn_row = tk.Frame(frame)
        btn_row.pack(fill="x", padx=8)
        tk.Button(btn_row, text="Add...", command=self._add_emulator).pack(side="left")
        tk.Button(btn_row, text="Edit selected...", command=self._edit_emulator).pack(side="left", padx=(4, 0))
        tk.Button(btn_row, text="Remove selected", command=self._remove_emulator).pack(side="left", padx=(4, 0))

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

        tk.Label(
            frame,
            text="iiSU's default AVD profile is a portrait phone screen, which\n"
            "looks cramped on a desktop. These settings change the emulated\n"
            "device's actual hardware profile (not a runtime overlay), so\n"
            "there's no letterboxing -- but applying them cold-boots the AVD.",
            fg="gray",
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(12, 12))

        display = self.config_data.get(
            "display", {"width": 1920, "height": 1080, "density": 240, "refresh_rate": 60}
        )

        tk.Label(frame, text="Width (px):").grid(row=1, column=0, sticky="w", padx=8)
        self.display_width_var = tk.StringVar(value=str(display.get("width", 1920)))
        tk.Entry(frame, textvariable=self.display_width_var, width=10).grid(
            row=1, column=1, sticky="w", padx=8, pady=2
        )

        tk.Label(frame, text="Height (px):").grid(row=2, column=0, sticky="w", padx=8)
        self.display_height_var = tk.StringVar(value=str(display.get("height", 1080)))
        tk.Entry(frame, textvariable=self.display_height_var, width=10).grid(
            row=2, column=1, sticky="w", padx=8, pady=2
        )

        tk.Label(frame, text="Density (dpi):").grid(row=3, column=0, sticky="w", padx=8)
        self.display_density_var = tk.StringVar(value=str(display.get("density", 240)))
        tk.Entry(frame, textvariable=self.display_density_var, width=10).grid(
            row=3, column=1, sticky="w", padx=8, pady=2
        )

        tk.Label(frame, text="Refresh rate (Hz):").grid(row=4, column=0, sticky="w", padx=8)
        self.display_refresh_var = tk.StringVar(value=str(display.get("refresh_rate", 60)))
        tk.Entry(frame, textvariable=self.display_refresh_var, width=10).grid(
            row=4, column=1, sticky="w", padx=8, pady=2
        )
        tk.Label(
            frame,
            text="Only affects iiSU's own UI smoothness inside the AVD -- actual\n"
            "gameplay runs in a separate native Windows emulator process, which\n"
            "already uses your monitor's real refresh rate with no setup needed.",
            fg="gray",
            justify="left",
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))

        tk.Button(
            frame, text="Auto-detect from primary monitor", command=self._autodetect_display
        ).grid(row=6, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 0))

        self.iisu_fullscreen_var = tk.BooleanVar(value=self.config_data.get("iisu_fullscreen", True))
        tk.Checkbutton(
            frame, text="Maximize the iiSU/AVD window automatically", variable=self.iisu_fullscreen_var
        ).grid(row=7, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 0))

        tk.Label(frame, text="AVD name:").grid(row=8, column=0, sticky="w", padx=8, pady=(12, 0))
        self.avd_name_var = tk.StringVar(value=self.config_data.get("avd_name", "medium_phone"))
        tk.Entry(frame, textvariable=self.avd_name_var, width=20).grid(
            row=9, column=0, sticky="w", padx=8, pady=(0, 8)
        )

        tk.Button(
            frame, text="Apply now (saves + cold-boots the AVD)", command=self._apply_display
        ).grid(row=10, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 0))
        self.display_status_label = tk.Label(frame, text="", fg="blue")
        self.display_status_label.grid(row=11, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 0))

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

        tk.Label(frame, text="iiSU window title match:").grid(row=0, column=0, sticky="w", padx=8, pady=(12, 0))
        self.window_title_var = tk.StringVar(value=self.config_data.get("iisu_window_title", ""))
        tk.Entry(frame, textvariable=self.window_title_var, width=40).grid(
            row=1, column=0, sticky="w", padx=8, pady=(0, 8)
        )

        tk.Label(frame, text="Bridge listen port:").grid(row=2, column=0, sticky="w", padx=8)
        self.port_var = tk.StringVar(value=str(self.config_data.get("bridge_port", 7737)))
        tk.Entry(frame, textvariable=self.port_var, width=10).grid(row=3, column=0, sticky="w", padx=8, pady=(0, 8))

        tk.Label(frame, text="Quit-to-frontend hotkey modifiers (ctrl/alt/shift/win, comma-separated):").grid(
            row=4, column=0, sticky="w", padx=8
        )
        hotkey = self.config_data.get("quit_hotkey", {"modifiers": ["ctrl", "alt"], "key": "q"})
        self.hotkey_mods_var = tk.StringVar(value=", ".join(hotkey.get("modifiers", [])))
        tk.Entry(frame, textvariable=self.hotkey_mods_var, width=30).grid(
            row=5, column=0, sticky="w", padx=8, pady=(0, 8)
        )

        tk.Label(frame, text="Quit-to-frontend hotkey key:").grid(row=6, column=0, sticky="w", padx=8)
        self.hotkey_key_var = tk.StringVar(value=hotkey.get("key", "q"))
        tk.Entry(frame, textvariable=self.hotkey_key_var, width=10).grid(
            row=7, column=0, sticky="w", padx=8, pady=(0, 8)
        )

        tk.Label(frame, text="Full-shutdown hotkey modifiers (closes iiSU and the AVD entirely):").grid(
            row=8, column=0, sticky="w", padx=8
        )
        shutdown_hotkey = self.config_data.get("shutdown_hotkey", {"modifiers": ["ctrl", "alt"], "key": "x"})
        self.shutdown_hotkey_mods_var = tk.StringVar(value=", ".join(shutdown_hotkey.get("modifiers", [])))
        tk.Entry(frame, textvariable=self.shutdown_hotkey_mods_var, width=30).grid(
            row=9, column=0, sticky="w", padx=8, pady=(0, 8)
        )

        tk.Label(frame, text="Full-shutdown hotkey key:").grid(row=10, column=0, sticky="w", padx=8)
        self.shutdown_hotkey_key_var = tk.StringVar(value=shutdown_hotkey.get("key", "x"))
        tk.Entry(frame, textvariable=self.shutdown_hotkey_key_var, width=10).grid(
            row=11, column=0, sticky="w", padx=8, pady=(0, 8)
        )

        tk.Label(
            frame,
            text="Port and hotkey changes need the bridge restarted to take effect\n"
            "(ROM directory, search folders, and emulator mappings apply on\n"
            "the very next game launch, no restart needed).",
            fg="gray",
            justify="left",
        ).grid(row=12, column=0, sticky="w", padx=8, pady=(8, 0))

    # -- Save -------------------------------------------------

    def save(self):
        original_emulators = self.config_data.get("emulators", {})
        emulators = {}
        for item in self.emulators_tree.get_children():
            prefix, exe_names_str, pre_args_str = self.emulators_tree.item(item, "values")
            # "by_extension" entries (e.g. com.retroarch, which maps to a
            # different real PC emulator per ROM extension rather than one
            # fixed exe) show up as blank rows here since this tree only
            # understands the plain exe_names/pre_args shape -- preserve the
            # original entry instead of overwriting it with an empty one.
            original = original_emulators.get(prefix, {})
            if "by_extension" in original and not exe_names_str.strip():
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
            "quit_hotkey": {
                "modifiers": [s.strip() for s in self.hotkey_mods_var.get().split(",") if s.strip()],
                "key": self.hotkey_key_var.get().strip() or "q",
            },
            "shutdown_hotkey": {
                "modifiers": [s.strip() for s in self.shutdown_hotkey_mods_var.get().split(",") if s.strip()],
                "key": self.shutdown_hotkey_key_var.get().strip() or "x",
            },
            "emulators": emulators,
        }

        save_config(self.config_data)
        self.status_label.config(text=f"Saved to {CONFIG_PATH.name}")
        self.after(3000, lambda: self.status_label.config(text=""))


if __name__ == "__main__":
    SetupApp().mainloop()
