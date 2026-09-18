"""
Default console -> PC emulator mappings, curated from iiSU's own bundled
emuladores_default.json (its list of consoles and, per console, which
Android packages it recognizes as compatible emulators).

Two shapes, matching bridge/config.json's "emulators" map:

STANDALONE_DEFAULTS: one Android package -> one PC executable. The
Android package chosen is iiSU's own top-priority candidate for that
console (the first "emulators" entry with a "packages" list) -- it's
stubbed (see installer/stub_apk.py) purely so iiSU's installed-package
check resolves that console to a package our patched LaunchBridge already
recognizes. What that Android package's real app would actually do is
irrelevant: our patch intercepts the launch before Android would ever
start it, and redirects to whatever PC executable is configured here
instead, regardless of whether the two projects are related at all (e.g.
PS2 is stubbed under AetherSX2's package but redirected to PCSX2 on PC --
there's no Android PCSX2 to begin with).

RETROARCH_BY_EXTENSION: consoles routed through a single shared
com.retroarch stub, disambiguated by the ROM's file extension the same
way bridge/launch_bridge.py already does for PS1/Dreamcast. Only
extensions that don't collide with another entry in this same map are
included here -- e.g. Saturn and MAME/arcade are deliberately left out,
since their extensions (.bin/.cue/.iso/.chd/.zip/.7z) overlap too broadly
with everything else on this list to disambiguate correctly from the
extension alone. Getting that right needs resolving the ROM's own console
folder, not just its extension, which is a bigger change than this list
is trying to be.

RetroArch itself is launched as retroarch.exe -L <core> <rom>, so pre_args
includes -L and a core path relative to wherever retroarch.exe is found
(standard "cores/xxx_libretro.dll" layout) -- this assumes the matching
core is already installed there, same as RetroArch itself needs to be
already installed for this to do anything.
"""

STANDALONE_DEFAULTS = [
    {
        "console": "psx",
        "console_label": "Sony PlayStation",
        "package": "com.github.stenzek.duckstation",
        "app_label": "DuckStation",
        "exe_names": ["duckstation-qt-x64-ReleaseLTCG.exe"],
        "pre_args": ["-fullscreen"],
    },
    {
        "console": "gc",
        "console_label": "Nintendo GameCube",
        "package": "org.dolphinemu.dolphinemu",
        "app_label": "Dolphin",
        "exe_names": ["Dolphin.exe", "DolphinQt2.exe"],
        "pre_args": ["-b"],
    },
    {
        "console": "wii",
        "console_label": "Nintendo Wii",
        "package": "org.dolphinemu.dolphinemu",
        "app_label": "Dolphin",
        "exe_names": ["Dolphin.exe", "DolphinQt2.exe"],
        "pre_args": ["-b"],
    },
    {
        "console": "wiiu",
        "console_label": "Nintendo Wii U",
        "package": "info.cemu.cemu",
        "app_label": "Cemu",
        "exe_names": ["Cemu.exe"],
        "pre_args": ["-f"],
    },
    {
        "console": "3ds",
        "console_label": "Nintendo 3DS",
        "package": "org.citra.citra_emu",
        "app_label": "Citra",
        "exe_names": ["citra-qt.exe"],
        "pre_args": ["-f"],
    },
    {
        "console": "3ds",
        "console_label": "Nintendo 3DS (Azahar)",
        "package": "org.azahar_emu.azahar",
        "app_label": "Azahar",
        # Azahar Plus (a further fork of Azahar) renamed its binary to
        # azahar.exe -- mainline Azahar builds still ship as citra-qt.exe,
        # inherited from Azahar's own Citra ancestry. Both are searched for
        # under this one slot since they're the same PC-side choice from
        # iiSU's perspective, just two forks' different binary names.
        "exe_names": ["citra-qt.exe", "azahar.exe"],
        "pre_args": ["-f"],
    },
    {
        "console": "psp",
        "console_label": "Sony PlayStation Portable",
        "package": "org.ppsspp.ppsspp",
        "app_label": "PPSSPP",
        "exe_names": ["PPSSPPWindows64.exe"],
        "pre_args": ["--fullscreen"],
    },
    {
        "console": "ps2",
        "console_label": "Sony PlayStation 2",
        "package": "xyz.aethersx2.android",
        "app_label": "PCSX2",
        "exe_names": ["pcsx2-qt.exe", "pcsx2.exe"],
        "pre_args": ["-fullscreen"],
    },
    {
        "console": "nds",
        "console_label": "Nintendo DS",
        "package": "me.magnum.melonds",
        "app_label": "melonDS",
        "exe_names": ["melonDS.exe"],
        "pre_args": [],
    },
    {
        "console": "dreamcast",
        "console_label": "Sega Dreamcast",
        "package": "com.flycast.emulator",
        "app_label": "Flycast",
        "exe_names": ["flycast.exe"],
        "pre_args": [],
    },
]

RETROARCH_PACKAGE = "com.retroarch"
RETROARCH_APP_LABEL = "RetroArch"

# iiSU lists RetroArch as its *first*-priority candidate for most consoles
# (including ones with a dedicated STANDALONE_DEFAULTS entry above, like
# PS1 and Dreamcast) -- if you ever explicitly pick "RetroArch" instead of
# the dedicated standalone option for one of those in iiSU's own settings,
# this is what keeps that launch redirecting somewhere real instead of
# trying to run a RetroArch that was only ever a stub.
RETROARCH_SAFETY_NET_EXTENSIONS = {
    ".cue": ("psx", ["duckstation-qt-x64-ReleaseLTCG.exe"], ["-fullscreen"]),
    ".bin": ("psx", ["duckstation-qt-x64-ReleaseLTCG.exe"], ["-fullscreen"]),
    ".pbp": ("psx", ["duckstation-qt-x64-ReleaseLTCG.exe"], ["-fullscreen"]),
    ".chd": ("psx", ["duckstation-qt-x64-ReleaseLTCG.exe"], ["-fullscreen"]),
    ".m3u": ("psx", ["duckstation-qt-x64-ReleaseLTCG.exe"], ["-fullscreen"]),
    ".cdi": ("dreamcast", ["flycast.exe"], []),
    ".gdi": ("dreamcast", ["flycast.exe"], []),
}

RETROARCH_BY_EXTENSION = [
    {
        "console": "nes",
        "console_label": "Nintendo Entertainment System",
        "core": "fceumm_libretro.dll",
        "extensions": [".nes", ".fds", ".unf", ".unif"],
    },
    {
        "console": "snes",
        "console_label": "Super Nintendo Entertainment System",
        "core": "snes9x_libretro.dll",
        "extensions": [".sfc", ".smc", ".bs", ".bsx", ".swc"],
    },
    {
        "console": "n64",
        "console_label": "Nintendo 64",
        "core": "mupen64plus_next_libretro.dll",
        "extensions": [".n64", ".z64", ".v64"],
    },
    {
        "console": "gba",
        "console_label": "Nintendo Game Boy Advance",
        "core": "mgba_libretro.dll",
        "extensions": [".gba"],
    },
    {
        "console": "gb",
        "console_label": "Nintendo Game Boy / Color",
        "core": "gambatte_libretro.dll",
        "extensions": [".gb", ".gbc"],
    },
    {
        "console": "genesis",
        "console_label": "Sega Genesis / Mega Drive",
        "core": "genesis_plus_gx_libretro.dll",
        "extensions": [".md", ".gen", ".smd", ".sms", ".gg", ".32x"],
    },
]


def build_emulators_map() -> dict:
    """Builds the full bridge/config.json "emulators" map from the two
    lists above. Standalone entries with the same package (e.g. GameCube
    and Wii both under Dolphin) collapse into one entry automatically."""
    emulators = {}
    for entry in STANDALONE_DEFAULTS:
        emulators[entry["package"]] = {
            "exe_names": entry["exe_names"],
            "pre_args": entry["pre_args"],
        }

    by_extension = {}
    for ext, (_console, exe_names, pre_args) in RETROARCH_SAFETY_NET_EXTENSIONS.items():
        by_extension[ext] = {"exe_names": exe_names, "pre_args": pre_args}
    for entry in RETROARCH_BY_EXTENSION:
        for ext in entry["extensions"]:
            by_extension[ext] = {
                "exe_names": ["retroarch.exe"],
                "pre_args": ["-L", f"cores/{entry['core']}", "-f"],
            }
    emulators[RETROARCH_PACKAGE] = {"by_extension": by_extension}

    return emulators


def all_stub_packages() -> list[tuple[str, str]]:
    """Every (package, app_label) that needs a redirector stub installed
    for these defaults to actually resolve in iiSU -- one per unique
    package, RetroArch included once even though it covers many consoles."""
    seen = {}
    for entry in STANDALONE_DEFAULTS:
        seen.setdefault(entry["package"], entry["app_label"])
    seen.setdefault(RETROARCH_PACKAGE, RETROARCH_APP_LABEL)
    return list(seen.items())


def all_emulator_exe_names() -> list[tuple[str, list[str]]]:
    """(app_label, exe_names) for every standalone emulator plus RetroArch
    itself, one per unique label -- for UIs that want to check which of
    these are actually installed under a set of search folders (see
    bridge/launch_bridge.py's find_executable, which this is meant to be
    used with for a result that matches what a real launch would find)."""
    seen = {}
    for entry in STANDALONE_DEFAULTS:
        seen.setdefault(entry["app_label"], entry["exe_names"])
    seen.setdefault(RETROARCH_APP_LABEL, ["retroarch.exe"])
    return list(seen.items())
