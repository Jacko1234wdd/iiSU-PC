"""
Applies config.json's "display" settings (width/height/density) to the AVD's
actual hardware profile and cold-boots it so the change takes effect.

This edits hw.lcd.width/height/density directly in the AVD's config.ini
rather than using the live `adb shell wm size` override: `wm size` only
resizes the logical pixel grid within the emulator's existing physical
panel shape, so going from a portrait phone profile to a landscape
resolution just letterboxes instead of giving a clean full-bleed display.
Changing the actual hardware profile requires a cold boot, but gives a
genuinely native resolution with no letterboxing.

Run this after changing display settings in config_editor.py's Advanced tab.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import winapi

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def avd_config_path(avd_name: str) -> Path:
    return Path.home() / ".android" / "avd" / f"{avd_name}.avd" / "config.ini"


def update_config_ini(path: Path, display: dict) -> None:
    width = display["width"]
    height = display["height"]
    density = display["density"]
    orientation = "landscape" if width >= height else "portrait"

    updates = {
        "hw.lcd.width": str(width),
        "hw.lcd.height": str(height),
        "hw.lcd.density": str(density),
        "hw.lcd.vsync": str(display.get("refresh_rate", 60)),
        "hw.initialOrientation": orientation,
        # A clean full-bleed display reads better fullscreen than a phone
        # bezel graphic around a small screen.
        "showDeviceFrame": "no",
    }

    lines = path.read_text(encoding="utf-8").splitlines()
    seen = set()
    new_lines = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else None
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            new_lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={value}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def main() -> None:
    config = load_config()
    avd_name = config["avd_name"]
    display = config["display"]

    config_ini = avd_config_path(avd_name)
    if not config_ini.is_file():
        print(f"Could not find AVD config at {config_ini}")
        sys.exit(1)

    print(
        f"Updating {config_ini} to {display['width']}x{display['height']} "
        f"@ {display['density']}dpi, {display.get('refresh_rate', 60)}Hz"
    )
    update_config_ini(config_ini, display)

    print(f"Stopping {avd_name} (if running)...")
    subprocess.run(["android", "emulator", "stop", avd_name], capture_output=True, text=True)
    time.sleep(2)

    print(f"Cold-booting {avd_name} with the new display profile...")
    result = subprocess.run(["android", "emulator", "start", avd_name, "--cold"], capture_output=True, text=True)
    if result.returncode != 0:
        print("Failed to start emulator:")
        print(result.stdout)
        print(result.stderr)
        sys.exit(1)

    print("Waiting for the iiSU window to appear...")
    hwnd = winapi.wait_for_window_by_title(config["iisu_window_title"], timeout=90.0)
    if hwnd is None:
        print("Emulator started, but couldn't find its window to bring to the foreground.")
        return

    winapi.force_foreground(hwnd, winapi.SW_RESTORE)
    if config.get("iisu_fullscreen"):
        winapi.make_fullscreen(hwnd)
        winapi.hide_emulator_toolbar()
    print("Done.")


if __name__ == "__main__":
    main()
