"""
Tears down everything start_iisu_pc.py starts (the launch bridge and the
AVD), plus anything else standing in the way of a clean slate. This is
what runs when you click Stop in the control panel (control_panel.py).

Tries a graceful `adb emu kill` first and gives qemu a few seconds to exit
on its own -- a clean exit is what lets it release its own lock files
(hardware-qemu.ini.lock, multiinstance.lock) under the portable AVD's own
directory (android-sdk-portable/avd-home/<name>.avd/, see portable_sdk.py).
Skipping straight to a force-kill leaves those locks behind and the *next*
start then fails immediately with "emulator.exe exited early (code 1)", so
force-taskkill is only a fallback for whatever the graceful path doesn't
manage to stop in time -- and even then, any leftover lock files are swept
away afterward so the next start isn't blocked by them.
"""

import json
import subprocess
import time
from pathlib import Path

from portable_sdk import PORTABLE_AVD_HOME

STATE_PATH = Path(__file__).parent / ".runtime_state.json"
CONFIG_PATH = Path(__file__).parent / "config.json"
GRACEFUL_STOP_TIMEOUT = 10  # seconds


def load_state() -> dict:
    if not STATE_PATH.is_file():
        return {}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def load_avd_name(state: dict) -> str | None:
    if "avd_name" in state:
        return state["avd_name"]
    if CONFIG_PATH.is_file():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f).get("avd_name")
    return None


def is_avd_running() -> bool:
    result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    return any(line.startswith("emulator-") and "device" in line for line in result.stdout.splitlines())


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True)


def kill_by_name(image_name: str) -> None:
    subprocess.run(["taskkill", "/IM", image_name, "/T", "/F"], capture_output=True, text=True)


def clear_stale_locks(avd_name: str | None) -> None:
    if not avd_name:
        return
    avd_dir = PORTABLE_AVD_HOME / f"{avd_name}.avd"
    if not avd_dir.is_dir():
        return
    for lock_path in avd_dir.glob("*.lock"):
        print(f"[stop] clearing stale lock {lock_path.name}...")
        if lock_path.is_dir():
            for child in lock_path.iterdir():
                child.unlink(missing_ok=True)
            lock_path.rmdir()
        else:
            lock_path.unlink(missing_ok=True)


def main() -> None:
    state = load_state()
    avd_name = load_avd_name(state)

    if is_avd_running():
        print("[stop] asking the AVD to shut down gracefully...")
        subprocess.run(["adb", "emu", "kill"], capture_output=True, text=True)
        deadline = time.time() + GRACEFUL_STOP_TIMEOUT
        while time.time() < deadline and is_avd_running():
            time.sleep(1)

    bridge_pid = state.get("bridge_pid")
    if bridge_pid is not None:
        print(f"[stop] killing bridge_pid {bridge_pid}...")
        kill_tree(bridge_pid)

    # Fallback sweep in case graceful shutdown didn't finish in time, the
    # state file is stale/missing, or a process got reparented away from
    # the PID we originally tracked (emulator.exe in particular tends to
    # leave a second shim process behind).
    for image_name in ("emulator.exe", "qemu-system-x86_64.exe"):
        print(f"[stop] sweeping any remaining {image_name}...")
        kill_by_name(image_name)

    clear_stale_locks(avd_name)

    if STATE_PATH.is_file():
        STATE_PATH.unlink()

    print("[stop] Done. Bridge and AVD should both be fully stopped now.")


if __name__ == "__main__":
    main()
