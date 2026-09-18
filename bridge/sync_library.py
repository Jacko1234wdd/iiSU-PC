"""
Mirrors the real ROM library (config.json's roms_dir, on the Windows/network
side) into the Android VM's storage as lightweight placeholder files, so
iiSU can scan and catalog the whole collection without needing the actual
multi-hundred-MB/GB ROM data pushed into the VM.

Why placeholders work: iiSU only needs a file to exist with the right name
to index it, scrape metadata for it (by filename), and build a launch
Intent referencing it. The actual gameplay never touches that file's
content -- our patched LaunchBridge redirects the launch to the bridge,
which finds the REAL file under roms_dir by matching filename and hands
that to the real PC emulator. So placeholders can be tiny (a few KB, not
0 bytes, in case iiSU's scanner distrusts empty files) and their content
is irrelevant.

Folder names matter though: iiSU only recognizes a folder as a console if
its name matches one of iiSU's own known console short/long/alternate
names (see console_names.json, extracted from iiSU's own bundled
emuladores_default.json). This script normalizes whatever your NAS calls
each console folder (e.g. "Playstation 1") into iiSU's expected form
(e.g. "psx") automatically.

Run this after adding/removing games in your real library, then hit
"Rescan full library" in iiSU.
"""

import json
import shlex
import subprocess
import sys
from pathlib import Path

from console_names import load_console_lookup, resolve_console_shortname

CONFIG_PATH = Path(__file__).parent / "config.json"

AVD_ROMS_ROOT = "/sdcard/Roms"
PLACEHOLDER_SIZE_KB = 4

IGNORE_TOP_LEVEL = {"folder.ico", "sync.ffs_lock"}


def adb(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["adb", *args], capture_output=True, text=True, check=check)


def main() -> None:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)

    roms_dir = Path(config["roms_dir"])
    if not roms_dir.is_dir():
        print(f"roms_dir '{roms_dir}' does not exist or isn't reachable.")
        sys.exit(1)

    exact, by_compact = load_console_lookup()

    script_lines = [f"rm -rf {shlex.quote(AVD_ROMS_ROOT)}"]
    console_count = 0
    file_count = 0
    skipped = []

    for console_folder in sorted(roms_dir.iterdir()):
        if console_folder.name in IGNORE_TOP_LEVEL or not console_folder.is_dir():
            continue

        shortname = resolve_console_shortname(console_folder.name, exact, by_compact)
        if shortname is None:
            skipped.append(console_folder.name)
            continue

        console_count += 1
        avd_console_root = f"{AVD_ROMS_ROOT}/{shortname}"
        script_lines.append(f"mkdir -p {shlex.quote(avd_console_root)}")

        for file_path in console_folder.rglob("*"):
            if file_path.is_dir():
                rel = file_path.relative_to(console_folder).as_posix()
                script_lines.append(f"mkdir -p {shlex.quote(f'{avd_console_root}/{rel}')}")
                continue
            rel = file_path.relative_to(console_folder).as_posix()
            avd_path = f"{avd_console_root}/{rel}"
            script_lines.append(
                f"dd if=/dev/zero of={shlex.quote(avd_path)} bs=1024 count={PLACEHOLDER_SIZE_KB} 2>/dev/null"
            )
            file_count += 1

    if skipped:
        print("Skipped folders with no matching iiSU console name (rename or add to NAS_NAME_OVERRIDES):")
        for name in skipped:
            print(f"  - {name}")

    if console_count == 0:
        print("No recognized console folders found under roms_dir; nothing to sync.")
        return

    script_text = "\n".join(script_lines) + "\n"
    local_script = Path(__file__).parent / "_sync_tmp.sh"
    local_script.write_text(script_text, encoding="utf-8", newline="\n")

    print(f"Pushing {console_count} console folder(s), {file_count} placeholder file(s) to the AVD...")
    adb("push", str(local_script), "/data/local/tmp/sync_library.sh")
    result = adb("shell", "sh /data/local/tmp/sync_library.sh", check=False)
    if result.returncode != 0:
        print("adb shell script failed:")
        print(result.stdout)
        print(result.stderr)
        sys.exit(1)

    local_script.unlink(missing_ok=True)
    print("Done. Now hit \"Rescan full library\" in iiSU's Library settings.")


if __name__ == "__main__":
    main()
