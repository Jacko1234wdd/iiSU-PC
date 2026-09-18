"""
One-shot launcher for the whole iiSU-PC setup: starts the AVD if it isn't
already running, then starts the launch bridge if it isn't already running.

This is the single entry point meant for day-to-day use -- it's what runs
when you click Start in the control panel (control_panel.py), instead of
manually starting the emulator and the bridge as separate steps.

Note: this intentionally does NOT use the `android emulator start` wrapper.
That command promises to "return when the emulator is fully started," but
hangs forever even after the AVD is fully booted and usable: it launches
emulator.exe as a grandchild and captures its output via a pipe, and
emulator.exe (the long-lived VM process) inherits that pipe's write end, so
the pipe's read side never sees EOF -- subprocess.run() then blocks forever
waiting for output that will never stop. Launching emulator.exe directly,
detached and with output discarded (not piped), avoids the whole class of
problem, and we poll `adb devices` ourselves to know when it's ready.

It also always launches from the portable SDK/AVD copy under
android-sdk-portable/ (see portable_sdk.py) rather than the system-wide
Android Studio install -- see portable_sdk.py for why.
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from portable_sdk import PORTABLE_AVD_HOME, PORTABLE_SDK, ensure_portable_sdk

CONFIG_PATH = Path(__file__).parent / "config.json"
BRIDGE_SCRIPT = Path(__file__).parent / "launch_bridge.py"
STATE_PATH = Path(__file__).parent / ".runtime_state.json"
EMULATOR_LOG_PATH = Path(__file__).parent / "emulator.log"

AVD_BOOT_TIMEOUT = 120  # seconds
MAX_LAUNCH_ATTEMPTS = 3
RETRY_DELAY = 5  # seconds

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f)


def is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def is_avd_running(avd_name: str) -> bool:
    result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    # A running AVD shows up as "emulator-5554\tdevice" (or similar) once booted.
    return any(line.startswith("emulator-") and "device" in line for line in result.stdout.splitlines())


def find_system_emulator_exe() -> Path | None:
    """Locates the existing Android Studio SDK install, used only as a
    one-time copy source for bootstrapping the portable copy -- actual
    launches always use the portable copy, never this."""
    candidates = [
        Path(os.environ.get("ANDROID_SDK_ROOT", "")) / "emulator" / "emulator.exe",
        Path(os.environ.get("ANDROID_HOME", "")) / "emulator" / "emulator.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "emulator" / "emulator.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def clear_stale_locks(avd_dir: Path) -> None:
    """emulator.exe refuses to start (exits immediately, code 1) if it finds
    lock files from a previous instance that didn't shut down cleanly --
    e.g. after a crash, a forced Task Manager kill, or closing the emulator
    window without going through adb. A clean `adb emu kill` releases these
    itself, but we can't guarantee every past shutdown was clean, so this
    clears them defensively before every launch."""
    if not avd_dir.is_dir():
        return
    for lock_path in avd_dir.glob("*.lock"):
        if lock_path.is_dir():
            for child in lock_path.iterdir():
                child.unlink(missing_ok=True)
            lock_path.rmdir()
        else:
            lock_path.unlink(missing_ok=True)


def diagnose_system_image(avd_dir: Path, sdk_root: str) -> None:
    """Prints hard evidence about the exact files emulator.exe just refused
    to accept, since its own "not a valid directory" / "Broken AVD system
    path" errors give no detail."""
    config_ini = avd_dir / "config.ini"
    if not config_ini.is_file():
        print(f"[start] diagnostic: {config_ini} not found")
        return
    sysdir = None
    for line in config_ini.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("image.sysdir.1="):
            sysdir = line.split("=", 1)[1].strip()
            break
    if sysdir is None:
        print("[start] diagnostic: image.sysdir.1 not found in config.ini")
        return
    image_dir = Path(sdk_root) / sysdir
    print(f"[start] diagnostic: checking {image_dir}")
    if not image_dir.is_dir():
        print("[start] diagnostic: directory does not exist right now")
        return
    for name in ("package.xml", "system.img", "build.prop"):
        path = image_dir / name
        if not path.is_file():
            print(f"[start] diagnostic: {name} is missing")
            continue
        try:
            with open(path, "rb") as f:
                f.read(16)
            print(f"[start] diagnostic: {name} ok ({path.stat().st_size} bytes, readable)")
        except OSError as e:
            print(f"[start] diagnostic: {name} exists but could not be read ({e}) -- likely locked by another process")


def build_usb_passthrough_args(usb_passthrough: list[dict]) -> list[str]:
    """Builds -usb-passthrough flags for real USB controllers (e.g. a PS5
    DualSense) so Android's own native gamepad driver (present since
    Android 12) handles them directly inside the guest -- no PC-side input
    translation needed for these, unlike Xbox-compatible controllers which
    go through controller_bridge.py's XInput polling instead. Matching by
    vendorid/productid alone (no hostbus/hostport) means it works from
    whichever USB port the controller happens to be plugged into, and is a
    no-op if the controller isn't currently connected -- confirmed via the
    emulator's own -help-usb-passthrough documentation."""
    args = []
    for device in usb_passthrough:
        args += ["-usb-passthrough", f"vendorid={device['vendorid']},productid={device['productid']}"]
    return args


def _launch_once(emulator_exe: Path, avd_name: str, env: dict, usb_passthrough: list[dict]) -> int | None:
    """One launch attempt. Logged to a real file, not a pipe: a pipe's write
    end would get inherited by this long-lived process and never see EOF
    (the same bug that made `android emulator start` hang), but a file has
    no such problem and still lets us show the real error on failure."""
    log_file = open(EMULATOR_LOG_PATH, "wb")
    try:
        process = subprocess.Popen(
            [str(emulator_exe), "-avd", avd_name, *build_usb_passthrough_args(usb_passthrough)],
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            close_fds=True,
            env=env,
        )
    finally:
        log_file.close()

    deadline = time.time() + AVD_BOOT_TIMEOUT
    while time.time() < deadline:
        if is_avd_running(avd_name):
            return process.pid
        if process.poll() is not None:
            print(f"[start] emulator.exe exited early (code {process.returncode}) before the AVD came up.")
            print(f"[start] see {EMULATOR_LOG_PATH} for details. Last lines:")
            tail = EMULATOR_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
            for line in tail:
                print(f"    {line}")
            return None
        time.sleep(2)
    print(f"[start] {avd_name} did not report ready within {AVD_BOOT_TIMEOUT}s.")
    return None


def start_avd(avd_name: str, usb_passthrough: list[dict]) -> int | None:
    """Launches the AVD directly (bypassing the buggy `android emulator
    start` wrapper) and returns its PID once it's confirmed running, so the
    stop script can find it reliably even if it later gets reparented.

    Always launches against the portable SDK/AVD copy under
    android-sdk-portable/, bootstrapping it from the system-wide Android
    Studio install on first run if it doesn't exist yet -- the system-wide
    install under %LOCALAPPDATA%\\Android\\Sdk has been unreliable, failing
    intermittently with "Broken AVD system path" even with the files
    verified present and ANDROID_SDK_ROOT passed explicitly. The portable
    copy lives in a plain folder next to this script instead."""
    system_emulator_exe = find_system_emulator_exe()
    if system_emulator_exe is None and not (PORTABLE_SDK / "emulator" / "emulator.exe").is_file():
        print("[start] Could not find an existing Android Studio emulator install to bootstrap the portable copy from.")
        return None

    try:
        env_overrides = ensure_portable_sdk(
            avd_name, system_emulator_exe.parent.parent if system_emulator_exe else None
        )
    except RuntimeError as e:
        print(f"[start] Failed to set up the portable SDK/AVD copy: {e}")
        return None

    emulator_exe = PORTABLE_SDK / "emulator" / "emulator.exe"
    avd_dir = PORTABLE_AVD_HOME / f"{avd_name}.avd"
    env = os.environ.copy()
    env.update(env_overrides)

    for attempt in range(1, MAX_LAUNCH_ATTEMPTS + 1):
        clear_stale_locks(avd_dir)
        pid = _launch_once(emulator_exe, avd_name, env, usb_passthrough)
        if pid is not None:
            return pid
        diagnose_system_image(avd_dir, env_overrides["ANDROID_SDK_ROOT"])
        if attempt < MAX_LAUNCH_ATTEMPTS:
            print(f"[start] attempt {attempt}/{MAX_LAUNCH_ATTEMPTS} failed, retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)
    return None


def main() -> None:
    config = load_config()
    avd_name = config["avd_name"]
    port = config["bridge_port"]
    state = {"avd_name": avd_name}

    if is_avd_running(avd_name):
        print(f"[start] {avd_name} is already running.")
    else:
        print(f"[start] Starting {avd_name}, this can take a minute...")
        pid = start_avd(avd_name, config.get("usb_passthrough", []))
        if pid is None:
            sys.exit(1)
        state["emulator_pid"] = pid
        print(f"[start] {avd_name} is up.")

    if is_port_open(port):
        print(f"[start] Bridge is already running on port {port}.")
    else:
        print("[start] Starting the launch bridge in its own window...")
        bridge_process = subprocess.Popen(
            [sys.executable, str(BRIDGE_SCRIPT)],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            cwd=str(BRIDGE_SCRIPT.parent),
        )
        state["bridge_pid"] = bridge_process.pid
        # Give it a moment to bind before reporting success.
        for _ in range(20):
            if is_port_open(port):
                break
            time.sleep(0.5)
        if is_port_open(port):
            print("[start] Bridge is up.")
        else:
            print("[start] Bridge didn't come up in time -- check its console window for errors.")

    save_state(state)
    print("[start] Ready. Launching a game in iiSU will now hand off to the real PC emulator.")


if __name__ == "__main__":
    main()
