"""
Completely removes everything Setup.bat and day-to-day use create on this
machine, so a fresh Setup.bat run afterward starts truly from scratch --
no reused SDK download, no reused AVD, no leftover config.

Stops the AVD/bridge first (if running) via bridge/stop_iisu_pc.py, then
removes:
  - bridge/'s generated state: the portable SDK+AVD copy, config.json,
    caches, the extracted icon, the last emulator.log
  - installer/'s generated state: its own SDK download, the patch
    keystore, the preserved build-tools copy, working directories
  - the actual AVD(s) under ~/.android/avd/ (and the stray per-AVD log
    directories the emulator leaves alongside it -- see NOTE below)
  - the desktop shortcut

Deliberately does NOT touch:
  - installer/input/*.apk -- that's your own supplied file, not
    something this project installed
  - installer/tools/apktool.jar -- a bundled project asset, not
    generated state
  - %LOCALAPPDATA%\\Android\\Sdk -- see the printed note at the end for
    why this is left alone by default

NOTE on ~/.android/avd/medium_phone.avd: sdk_bootstrap.py creates the
AVD under Android's own hardcoded device-profile name first and renames
it afterward (`android emulator create` doesn't support naming it
directly) -- an interrupted first-time setup can leave that intermediate
name behind before the rename happens, so it's cleaned up defensively
alongside whatever the real configured name is.

Usage:
    python uninstall.py [--yes]
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

INSTALLER_DIR = Path(__file__).parent
PROJECT_ROOT = INSTALLER_DIR.parent
BRIDGE_DIR = PROJECT_ROOT / "bridge"

sys.path.insert(0, str(INSTALLER_DIR))
from sdk_bootstrap import DEVICE_PROFILE
from setup_wizard import DEFAULT_AVD_NAME

sys.path.insert(0, str(BRIDGE_DIR))


def _dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if not path.is_dir():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _remove(path: Path, attempts: int = 5, delay: float = 1.0) -> int:
    """Removes a file or directory tree, retrying briefly on a locked
    file -- a process that was just stopped doesn't always release its
    handles the instant it exits (confirmed live: this raced and left
    ~1GB behind on the first attempt during testing). Returns the size
    reclaimed, 0 if the path didn't exist or couldn't be removed."""
    if not path.exists():
        return 0
    size = _dir_size(path)
    for attempt in range(attempts):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            return size
        except OSError:
            if attempt == attempts - 1:
                print(f"  ! couldn't remove {path} -- still locked, remove it by hand once nothing's using it")
                return 0
            time.sleep(delay)
    return 0


def stop_running_instance() -> None:
    """Run first, before anything else is deleted -- stop_iisu_pc.py
    needs bridge/config.json (for the real avd_name) and
    .runtime_state.json (for the tracked PIDs) to do a clean shutdown,
    both of which this script is about to remove."""
    if not (BRIDGE_DIR / "config.json").is_file() and not (BRIDGE_DIR / ".runtime_state.json").is_file():
        return
    print("[uninstall] stopping the AVD and bridge (if running)...")
    try:
        import stop_iisu_pc
        stop_iisu_pc.main()
    except Exception as e:
        print(f"[uninstall] couldn't run a clean stop ({e}) -- falling back to a process sweep")
        subprocess.run(["taskkill", "/IM", "emulator.exe", "/T", "/F"], capture_output=True)
        subprocess.run(["taskkill", "/IM", "qemu-system-x86_64.exe", "/T", "/F"], capture_output=True)


def detect_avd_name() -> str:
    config_path = BRIDGE_DIR / "config.json"
    if config_path.is_file():
        try:
            import json
            return json.loads(config_path.read_text(encoding="utf-8")).get("avd_name", DEFAULT_AVD_NAME)
        except Exception:
            pass
    return DEFAULT_AVD_NAME


def remove_avd(avd_name: str, total: list) -> None:
    avd_home = Path.home() / ".android" / "avd"
    for name in {avd_name, DEVICE_PROFILE}:
        total[0] += _remove(avd_home / f"{name}.avd")
        total[0] += _remove(avd_home / f"{name}.ini")
        # The emulator's own per-AVD scratch/log directory, separate from
        # the *.avd config folder itself (e.g. ~/.android/iisuwin/).
        total[0] += _remove(Path.home() / ".android" / name)


def remove_desktop_shortcut(total: list) -> None:
    try:
        import create_shortcut
        shortcut_path = create_shortcut.desktop_dir() / create_shortcut.SHORTCUT_NAME
    except Exception:
        shortcut_path = Path.home() / "Desktop" / "iiSU-PC.lnk"
    total[0] += _remove(shortcut_path)


def main() -> None:
    print("=== iiSU-PC uninstall ===\n")
    print("This removes the Android VM, its SDK, your bridge config, the signing")
    print("keystore, and the desktop shortcut. It does NOT touch your ROM library,")
    print("your PC emulators, or the iiSU APK you supplied in installer/input/.\n")

    if "--yes" not in sys.argv:
        answer = input("Type 'yes' to continue: ").strip().lower()
        if answer != "yes":
            print("Cancelled -- nothing was removed.")
            return

    avd_name = detect_avd_name()
    stop_running_instance()

    total = [0]
    print("\n[uninstall] removing bridge/ generated state...")
    for rel in [
        "android-sdk-portable", "config.json", ".path_cache.json",
        ".runtime_state.json", "emulator.log", ".iisu_icon.ico", "_icon_extract_tmp",
    ]:
        total[0] += _remove(BRIDGE_DIR / rel)

    print("[uninstall] removing installer/ generated state...")
    for rel in [
        "android-sdk", "_work", "_cmdline_tools_extract",
        "commandlinetools.zip", "keystore", "tools/build-tools",
    ]:
        total[0] += _remove(INSTALLER_DIR / rel)

    print(f"[uninstall] removing the '{avd_name}' AVD...")
    remove_avd(avd_name, total)

    print("[uninstall] removing the desktop shortcut...")
    remove_desktop_shortcut(total)

    print(f"\n=== Done -- reclaimed {total[0] / 1e9:.1f} GB ===")
    print(f"Kept: installer/input/*.apk (your own file) and installer/tools/apktool.jar (a project asset).")
    print(
        "\nNot touched: %LOCALAPPDATA%\\Android\\Sdk. Depending on how the SDK\n"
        "downloader's underlying tool resolves its install root, packages can end\n"
        "up there instead of (or alongside) installer/android-sdk/ -- if you don't\n"
        "have a real Android Studio install of your own and want that reclaimed\n"
        "too, check for build-tools/34.0.0 and\n"
        "system-images/android-36/google_apis_playstore/x86_64 there before\n"
        "deleting it, since a real install would have those same packages for an\n"
        "unrelated reason."
    )


if __name__ == "__main__":
    main()
