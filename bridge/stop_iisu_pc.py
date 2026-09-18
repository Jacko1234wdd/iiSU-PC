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

Also deletes any snapshot state left behind by the shutdown itself (see
clear_snapshots()) -- this AVD always cold-boots, so a saved snapshot is
just multi-GB dead weight, never something that gets loaded.
"""

import json
import shutil
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


def _remove_path_with_retry(path: Path, attempts: int = 5, delay: float = 1.0) -> None:
    """A process that just got taskkilled doesn't always release its file
    handle the instant it exits -- Windows can hold a lock file for a
    moment longer (confirmed live: this raced and crashed the whole
    shutdown on the very first real test). Retrying briefly avoids that
    for what's normally a sub-second timing gap, without ever blocking
    indefinitely if something is genuinely still holding it."""
    for attempt in range(attempts):
        try:
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink(missing_ok=True)
            return
        except OSError:
            if attempt == attempts - 1:
                print(f"[stop] couldn't remove {path.name}, leaving it -- the next start will retry")
                return
            time.sleep(delay)


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
                _remove_path_with_retry(child)
            _remove_path_with_retry(lock_path)
        else:
            _remove_path_with_retry(lock_path)


def clear_snapshots(avd_name: str | None) -> None:
    """start_iisu_pc.py always cold-boots (-no-snapshot, forceColdBoot=yes,
    quickbootChoice.ini pinned to saveOnExit=false -- see portable_sdk.py),
    so a saved snapshot is never going to be loaded by anything. It gets
    written anyway: `adb emu kill`'s own shutdown path saves one
    regardless of all three of those settings (confirmed live, a multi-GB
    default_boot snapshot reappeared even with every documented way to
    disable it in place). Deleting it here, every time, is a multi-GB
    disk leak fix rather than fighting an emulator behavior that doesn't
    follow its own documented flags -- and it's also exactly the kind of
    stale, no-longer-matching-reality VM state a resumed snapshot would
    otherwise carry forward (e.g. mounts reflecting whatever was true when
    it was captured, not what's true now)."""
    avd_dir = PORTABLE_AVD_HOME / f"{avd_name}.avd" if avd_name else None
    if avd_dir is None or not avd_dir.is_dir():
        return
    snapshots_dir = avd_dir / "snapshots"
    if snapshots_dir.is_dir():
        print("[stop] removing snapshot state (never loaded -- this AVD always cold-boots)...")
        shutil.rmtree(snapshots_dir, ignore_errors=True)


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
    clear_snapshots(avd_name)

    if STATE_PATH.is_file():
        STATE_PATH.unlink()

    print("[stop] Done. Bridge and AVD should both be fully stopped now.")


if __name__ == "__main__":
    main()
