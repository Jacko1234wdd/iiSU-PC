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
- Optional: [Pillow](https://pypi.org/project/pillow/) (`pip install pillow`) if you want the desktop shortcut Setup.bat creates to use iiSU's own icon (extracted from your APK) instead of a generic one

## First-time setup

1. Drop your iiSU APK into `installer/input/` (any filename, `.apk` extension) -- or just leave it wherever it already is and use the "Browse..." button once `Setup.bat` opens; either way works the whole way through, including the desktop shortcut's icon.
2. Run `Setup.bat` (in this folder).

This downloads and sets up a self-contained Android SDK and virtual device (nothing touches any existing Android Studio install), patches your APK, gets it installed, installs a redirector app for every console `shared/emulator_defaults.py` knows about, and creates a desktop shortcut that launches straight into iiSU. It can take a while and several GB on first run.

Once it's done, a short step-by-step onboarding wizard opens automatically — ROM directory, emulator search folders (with a button to scan for what's already installed), the emulator-to-package mappings themselves (editable in case you're running an unusual fork, e.g. one that ships as a differently-named .exe), display resolution, and hotkeys, one screen at a time with live feedback, finishing with a summary before it saves anything. There's no separate manual-configuration step to remember afterward; `config_editor.py`'s full tabbed editor is still there later for anything the wizard doesn't cover.

Once everything's confirmed working, the installer deletes its own copy of the Android SDK (`installer/android-sdk/`, ~3.7GB) since `bridge/`'s portable copy has everything it needs going forward. The tradeoff: re-running `Setup.bat` later for a *different* iiSU APK re-downloads that SDK from scratch rather than reusing it.

## Day to day use

Double-click the **desktop shortcut** Setup.bat created to launch straight into iiSU, or run **`iiSU-PC.bat`** (in this folder) for the control panel — live status, Start/Stop, and a button into the ROM directory / PC emulator / hotkey / display settings.

Every start re-syncs your ROM library into the VM automatically, so adding or removing games just means starting iiSU-PC again — no separate step. It's a no-op if nothing's changed since the last sync (checked by comparing a fingerprint of your library against one saved in the VM itself, so it stays correct even if the VM gets rebuilt independently), so this doesn't add noticeable startup time for a large library on its second and later starts. iiSU itself still needs to notice the change: hit "Rescan full library" in its Library settings after your first start with a new game.

Inside the VM, `Ctrl+Alt+Q` force-quits the current game and returns to iiSU; `Ctrl+Alt+X` closes iiSU and shuts down the VM entirely (both rebindable in Configure). Holding **Back+Start** together on a controller for 2.5s does the same full shutdown, no keyboard needed.

## Uninstalling

Run **`Uninstall.bat`** (in this folder) to remove everything Setup.bat and day-to-day use created: the Android VM and its portable SDK copy, `bridge/config.json`, the signing keystore, and the desktop shortcut. It does not touch your ROM library, your PC emulators, or the iiSU APK you supplied in `installer/input/`. It'll also print a note about `%LOCALAPPDATA%\Android\Sdk`, which the SDK downloader can end up writing into depending on how its underlying tool resolves its install root — left alone by default since a real Android Studio install would keep its own SDK there too.

## How it works, briefly

`installer/patch_iisu.py` decompiles your iiSU APK, redirects its ROM-launch code to a small injected class that sends the launch request to `bridge/launch_bridge.py` over a local socket, then rebuilds and signs it with a key generated just for your install. The bridge matches the requested game to a PC emulator (configured in `bridge/config.json`) and launches it directly on Windows.

Before any of that can happen, though, iiSU needs to think a real emulator is installed for each console -- it checks for one of a few known Android package names before it'll treat a console as playable. Setup installs a placeholder "redirector" app for each one (`installer/stub_apk.py`, built from `shared/emulator_defaults.py`'s curated console list) -- it does nothing itself, since the patched launch never reaches it, but its presence (with a real icon, so it doesn't look out of place next to actual apps in iiSU's own "Installed Emulators" list) is what makes iiSU offer that console at all. `config_editor.py`'s "Install Redirector Apps..." button re-runs this any time (e.g. after adding a console's emulator by hand).

## Project layout

```
Setup.bat, iiSU-PC.bat, Uninstall.bat   entry points
shared/theme.py            the dark/gradient look shared by both GUIs
shared/emulator_defaults.py  curated console -> PC emulator mappings, and which need a redirector

installer/
  setup_wizard.py          first-time setup, called by setup_gui.py and usable from the CLI
  setup_gui.py             GUI front end for setup_wizard.py
  sdk_bootstrap.py         downloads/installs the Android SDK and creates the AVD
  patch_iisu.py            decompiles, patches, rebuilds, and signs your iiSU APK
  smali_patch/             the injected LaunchBridge classes patch_iisu.py adds to iiSU
  stub_apk.py              builds/installs the placeholder "redirector" apps (see below)
  stub_apk_template/       the (identical, per-package-renamed) redirector app project
  uninstall.py             removes everything Setup.bat and day-to-day use create (see Uninstalling)

bridge/
  control_panel.py         day-to-day GUI: status, Start/Stop, opens config_editor.py
  onboarding_wizard.py     step-by-step first-run setup, launched automatically after Setup.bat
  config_editor.py         tabbed GUI for editing config.json later (ROM dir, emulators, display, hotkeys)
  bridge_config.py         shared config.json loader (used by everything below)
  apply_display.py         applies config.json's display settings to the AVD and cold-boots it
  start_iisu_pc.py         boots the AVD (if needed) and starts launch_bridge.py
  stop_iisu_pc.py          tears both back down
  launch_bridge.py         listens for launch requests from the patched APK, runs the PC emulator
  controller_bridge.py     forwards controller input into the AVD; Back+Start closes everything
  portable_sdk.py          copies the SDK/AVD into a self-contained folder under bridge/
  sync_library.py          mirrors your real ROM library into the AVD as scan-only placeholders -- runs automatically on every start, skipping the rebuild if nothing changed
  console_names.py         resolves a ROM folder name to one of iiSU's known consoles
  create_shortcut.py       creates the desktop shortcut, extracting iiSU's icon from your APK
  winapi.py                shared Win32 window-management helpers
```

## If something breaks

- `installer/patch_iisu.py`'s patch is anchored on a specific log string in iiSU's code. If iiSU updates and changes that code, the patch will fail loudly with a clear error rather than silently producing a broken build — it needs updating by hand at that point, not just a re-run.
- `bridge/emulator.log` has the Android emulator's own output if the VM won't boot.
- Re-running `Setup.bat` is safe — it skips anything already done (SDK, AVD, keystore) and won't overwrite an existing `bridge/config.json`'s ROM directory/emulator settings.
- The AVD always cold-boots and never keeps a resume snapshot around (removed automatically after every clean Stop) — a resumed snapshot can carry forward storage/mount state that's since gone stale, so this trades a bit of boot time for not hitting that class of bug.
