# iiSU-PC Setup

Runs iiSU (an Android emulation frontend) inside a Windows-hosted Android VM, patched so launching a game in iiSU hands off to a real PC emulator instead of an Android one.

**This does not include iiSU itself.** iiSU is closed-source, third-party software this project has no affiliation with — you need your own copy of its APK. This tool patches *your* copy, the same way any APK-patching/modding tool works; it never bundles or redistributes iiSU's binary.

## Requirements

- Windows 10/11 (64-bit)
- A JDK on PATH (`java` and `keytool` need to work from a terminal) — e.g. [Eclipse Temurin](https://adoptium.net/)
- Python 3.11+
- Your own copy of the iiSU APK
- Whichever PC emulators you actually want to use (DuckStation, Dolphin, PCSX2, etc.) — install these yourself; this tool doesn't bundle them either
- A few GB of free disk space and a decent internet connection (first run downloads the Android SDK + a system image)
- Optional: [Pillow](https://pypi.org/project/pillow/) (`pip install pillow`) if you want the "Desktop Shortcut" button to use iiSU's own icon (extracted from your APK) instead of a generic one

## First-time setup

1. Drop your iiSU APK into `installer/input/` (any filename, `.apk` extension).
2. Run `Setup.bat` (in this folder).

This downloads and sets up a self-contained Android SDK and virtual device (nothing touches any existing Android Studio install), patches your APK, and gets it installed. It can take a while and several GB on first run.

Once everything's confirmed working, the installer deletes its own copy of the Android SDK (`installer/android-sdk/`, ~3.7GB) since `bridge/`'s portable copy has everything it needs going forward. The tradeoff: re-running `Setup.bat` later for a *different* iiSU APK re-downloads that SDK from scratch rather than reusing it.

## Day to day use

Run **`iiSU-PC.bat`** (in this folder) — one control panel with live status, Start/Stop, a button into the ROM directory / PC emulator / hotkey / display settings, and a button to create a desktop shortcut that launches straight into iiSU (skipping the control panel).

Inside the VM, `Ctrl+Alt+Q` force-quits the current game and returns to iiSU; `Ctrl+Alt+X` closes iiSU and shuts down the VM entirely (both rebindable in Configure). Holding **Back+Start** together on a controller for 2.5s does the same full shutdown, no keyboard needed.

## How it works, briefly

`installer/patch_iisu.py` decompiles your iiSU APK, redirects its ROM-launch code to a small injected class that sends the launch request to `bridge/launch_bridge.py` over a local socket, then rebuilds and signs it with a key generated just for your install. The bridge matches the requested game to a PC emulator (configured in `bridge/config.json`) and launches it directly on Windows.

## Project layout

```
Setup.bat, iiSU-PC.bat     entry points -- launch the two GUIs below
shared/theme.py            the dark/gradient look shared by both GUIs

installer/
  setup_wizard.py          first-time setup, called by setup_gui.py and usable from the CLI
  setup_gui.py             GUI front end for setup_wizard.py
  sdk_bootstrap.py         downloads/installs the Android SDK and creates the AVD
  patch_iisu.py            decompiles, patches, rebuilds, and signs your iiSU APK
  smali_patch/             the injected LaunchBridge classes patch_iisu.py adds to iiSU

bridge/
  control_panel.py         day-to-day GUI: status, Start/Stop, opens config_editor.py
  config_editor.py         GUI for editing config.json (ROM dir, emulators, display, hotkeys)
  bridge_config.py         shared config.json loader (used by everything below)
  start_iisu_pc.py         boots the AVD (if needed) and starts launch_bridge.py
  stop_iisu_pc.py          tears both back down
  launch_bridge.py         listens for launch requests from the patched APK, runs the PC emulator
  controller_bridge.py     forwards controller input into the AVD; Back+Start closes everything
  portable_sdk.py          copies the SDK/AVD into a self-contained folder under bridge/
  sync_library.py          mirrors your real ROM library into the AVD as scan-only placeholders
  console_names.py         resolves a ROM folder name to one of iiSU's known consoles
  create_shortcut.py       creates the desktop shortcut, extracting iiSU's icon from your APK
  winapi.py                shared Win32 window-management helpers
```

## If something breaks

- `installer/patch_iisu.py`'s patch is anchored on a specific log string in iiSU's code. If iiSU updates and changes that code, the patch will fail loudly with a clear error rather than silently producing a broken build — it needs updating by hand at that point, not just a re-run.
- `bridge/emulator.log` has the Android emulator's own output if the VM won't boot.
- Re-running `Setup.bat` is safe — it skips anything already done (SDK, AVD, keystore) and won't overwrite an existing `bridge/config.json`'s ROM directory/emulator settings.
