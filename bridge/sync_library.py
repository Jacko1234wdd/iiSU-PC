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

Runs automatically on every start (see start_iisu_pc.py), and skips the
actual rebuild whenever nothing's changed since the last one -- for a
large library, the slow part is never walking the real filesystem (fast
even for tens of thousands of files), it's running one adb shell command
per placeholder file inside the guest. The "last synced" signal lives
*inside* the AVD itself (a fingerprint file dropped alongside the
placeholders), not a local cache file here: a local cache would go stale
the moment the AVD gets wiped or rebuilt independently of the real
library changing, silently leaving it with no ROMs at all and no sign
why. Reading the fingerprint back out of the AVD instead means the
"is this still current" question is always answered by what's actually
there, never by a guess about it.
"""

import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

from console_names import load_console_lookup, resolve_console_shortname

CONFIG_PATH = Path(__file__).parent / "config.json"

AVD_ROMS_ROOT = "/sdcard/Roms"
FINGERPRINT_PATH = f"{AVD_ROMS_ROOT}/.sync_fingerprint"
PLACEHOLDER_SIZE_KB = 4

IGNORE_TOP_LEVEL = {"folder.ico", "sync.ffs_lock"}


def adb(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["adb", *args], capture_output=True, text=True, check=check)


def scan_library(roms_dir: Path, exact: dict, by_compact: dict) -> tuple[dict[str, list[tuple[str, int, int]]], list[str]]:
    """Walks roms_dir once, grouping recognized console folders' files by
    iiSU short name with (relative path, size, mtime) for each -- both
    what's needed to build the sync script AND to fingerprint the library
    for change detection come from this one walk."""
    consoles: dict[str, list[tuple[str, int, int]]] = {}
    skipped = []
    for console_folder in sorted(roms_dir.iterdir()):
        if console_folder.name in IGNORE_TOP_LEVEL or not console_folder.is_dir():
            continue

        shortname = resolve_console_shortname(console_folder.name, exact, by_compact)
        if shortname is None:
            skipped.append(console_folder.name)
            continue

        entries = []
        for file_path in console_folder.rglob("*"):
            if file_path.is_dir():
                continue
            rel = file_path.relative_to(console_folder).as_posix()
            st = file_path.stat()
            entries.append((rel, st.st_size, int(st.st_mtime)))
        entries.sort()
        consoles.setdefault(shortname, []).extend(entries)

    return consoles, skipped


def fingerprint(roms_dir: Path, consoles: dict[str, list[tuple[str, int, int]]]) -> str:
    """A stable hash of everything that would change what gets synced --
    which consoles, and each file's relative path/size/mtime."""
    h = hashlib.sha256()
    h.update(str(roms_dir).encode("utf-8"))
    for shortname in sorted(consoles):
        h.update(f"\n#{shortname}\n".encode("utf-8"))
        for rel, size, mtime in consoles[shortname]:
            h.update(f"{rel}|{size}|{mtime}\n".encode("utf-8"))
    return h.hexdigest()


def read_avd_fingerprint() -> str | None:
    result = adb("shell", f"cat {shlex.quote(FINGERPRINT_PATH)}", check=False)
    return result.stdout.strip() or None


def main() -> None:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)

    roms_dir = Path(config["roms_dir"])
    if not roms_dir.is_dir():
        print(f"roms_dir '{roms_dir}' does not exist or isn't reachable.")
        sys.exit(1)

    exact, by_compact = load_console_lookup()
    consoles, skipped = scan_library(roms_dir, exact, by_compact)

    if skipped:
        print("Skipped folders with no matching iiSU console name (rename or add to NAS_NAME_OVERRIDES):")
        for name in skipped:
            print(f"  - {name}")

    if not consoles:
        print("No recognized console folders found under roms_dir; nothing to sync.")
        return

    file_count = sum(len(entries) for entries in consoles.values())
    current_fingerprint = fingerprint(roms_dir, consoles)
    if read_avd_fingerprint() == current_fingerprint:
        print(f"Library unchanged ({file_count} file(s) across {len(consoles)} console(s)) -- skipping resync.")
        return

    script_lines = [f"rm -rf {shlex.quote(AVD_ROMS_ROOT)}"]
    for shortname, entries in consoles.items():
        avd_console_root = f"{AVD_ROMS_ROOT}/{shortname}"
        script_lines.append(f"mkdir -p {shlex.quote(avd_console_root)}")
        seen_dirs = set()
        for rel, _size, _mtime in entries:
            avd_path = f"{avd_console_root}/{rel}"
            parent = str(Path(avd_path).parent.as_posix())
            if parent not in seen_dirs:
                script_lines.append(f"mkdir -p {shlex.quote(parent)}")
                seen_dirs.add(parent)
            script_lines.append(
                f"dd if=/dev/zero of={shlex.quote(avd_path)} bs=1024 count={PLACEHOLDER_SIZE_KB} 2>/dev/null"
            )
    # Written last, inside the same script, so it only lands once
    # everything else has actually succeeded.
    script_lines.append(f"echo {shlex.quote(current_fingerprint)} > {shlex.quote(FINGERPRINT_PATH)}")

    script_text = "\n".join(script_lines) + "\n"
    local_script = Path(__file__).parent / "_sync_tmp.sh"
    local_script.write_text(script_text, encoding="utf-8", newline="\n")

    print(f"Pushing {len(consoles)} console folder(s), {file_count} placeholder file(s) to the AVD...")
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
