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
- Optional: [Pillow](https://pypi.org/project/pillow/) (`pip install pillow`) for two cosmetic extras that degrade gracefully without it — the desktop shortcut using iiSU's own icon (extracted from your APK) instead of a generic one, and the Manager's Credits page showing real circular GitHub avatars instead of plain colored circles

## First-time setup

1. Drop your iiSU APK into `installer/input/` (any filename, `.apk` extension) -- or just leave it wherever it already is and use the "Browse..." button once Setup opens; either way works the whole way through, including the desktop shortcut's icon.
2. Run **`iiSU-PC Manager.bat`** (in the `bridge/` folder) and click **Run Setup** on its Home page -- or run `Setup.bat` (in `installer/`) directly if you'd rather skip straight to it without opening the Manager first.

This checks your APK is actually iiSU and that you have enough free disk space before doing anything slow, then downloads and sets up a self-contained Android SDK and virtual device (nothing touches any existing Android Studio install), patches your APK, gets it installed, installs a redirector app for every console `shared/emulator_defaults.py` knows about, and creates a desktop shortcut that launches straight into iiSU. It shows which of its 7 steps is currently running, since it can take a while and several GB on first run.

Once it's done, a short step-by-step onboarding wizard opens automatically — ROM directory, emulator search folders (with a button to scan for what's already installed), the emulator-to-package mappings themselves (editable in case you're running an unusual fork, e.g. one that ships as a differently-named .exe), display resolution, and hotkeys, one screen at a time with live feedback, finishing with a summary (including a flag for any emulator that scan never found) before it saves anything. There's no separate manual-configuration step to remember afterward; the Manager's settings pages are still there later for anything the wizard doesn't cover, and its Home page automatically switches from "Run Setup" to "Open" once setup finishes.

Once everything's confirmed working, the installer deletes its own copy of the Android SDK (`installer/android-sdk/`, ~3.7GB) since `bridge/`'s portable copy has everything it needs going forward. The tradeoff: re-running setup later for a *different* iiSU APK re-downloads that SDK from scratch rather than reusing it.

## Day to day use

Double-click the **desktop shortcut** Setup created to launch straight into iiSU, or run **`iiSU-PC Manager.bat`** (in `bridge/`) for the full Manager -- one window covering everything, navigated with the hamburger (☰) sidebar instead of several separate tools.

Every start (either path) checks for updates first (`bridge/updater.py`). If this is a git checkout, it fetches and fast-forwards the branch you're actually on (dev stays on dev, master stays on master, no configuration needed) -- always a no-op unless it's a clean update, so uncommitted local changes never get clobbered, just left alone with a note to `git pull` by hand. A plain downloaded/extracted install (no `.git` folder) instead compares `VERSION` against the latest GitHub Release and only prints a link -- it never modifies files in place. Either way this can't make the run in progress use the new code; it just means the *next* start will.

- **Home** -- live AVD/bridge status, the Open/Stop button, a running status line during Start/Stop (not just a spinner), and quick buttons to your ROMs folder and the logs folder (the AVD, bridge, and shutdown-hotkey processes all run without a visible console window, logging to `emulator.log`/`bridge.log`/`stop.log` instead).
- **ROM Directory**, **Emulators**, **Display**, **Advanced** -- everything `config.json` holds, edited here and saved with one Save button at the bottom. The Emulators page's "Test Selected..." button checks where a mapping resolves to (and whether that executable is actually found) without starting the AVD.
- **Credits** -- who built this and how (see below).
- **Uninstall** -- tucked below a divider at the bottom of the sidebar since it's not an everyday action; see Uninstalling.

Every start re-syncs your ROM library into the VM automatically, so adding or removing games just means starting iiSU-PC again — no separate step. It's a no-op if nothing's changed since the last sync (checked by comparing a fingerprint of your library against one saved in the VM itself, so it stays correct even if the VM gets rebuilt independently), so this doesn't add noticeable startup time for a large library on its second and later starts. iiSU itself still needs to notice the change: hit "Rescan full library" in its Library settings after your first start with a new game.

Inside the VM, `Ctrl+Alt+Q` force-quits the current game and returns to iiSU; `Ctrl+Alt+X` closes iiSU and shuts down the VM entirely (both rebindable in Advanced). Holding **Back+Start** together on a controller for 2.5s does the same full shutdown, no keyboard needed.

## Uninstalling

Either open the Manager's **Uninstall** page (bottom of the sidebar) for a graphical version with a live preview of exactly what will be removed and how much space it frees before you confirm, or run **`Uninstall.bat`** (in `installer/`) for the same thing from the command line. Both remove the Android VM and its portable SDK copy, `bridge/config.json`, the signing keystore, and the desktop shortcut. Neither touches your ROM library, your PC emulators, or the iiSU APK you supplied in `installer/input/`. Both also print a note about `%LOCALAPPDATA%\Android\Sdk`, which the SDK downloader can end up writing into depending on how its underlying tool resolves its install root — left alone by default since a real Android Studio install would keep its own SDK there too.

## How it works, briefly

`installer/patch_iisu.py` decompiles your iiSU APK, redirects its ROM-launch code to a small injected class that sends the launch request to `bridge/launch_bridge.py` over a local socket, then rebuilds and signs it with a key generated just for your install. The bridge matches the requested game to a PC emulator (configured in `bridge/config.json`) and launches it directly on Windows.

Before any of that can happen, though, iiSU needs to think a real emulator is installed for each console -- it checks for one of a few known Android package names before it'll treat a console as playable. Setup installs a placeholder "redirector" app for each one (`installer/stub_apk.py`, built from `shared/emulator_defaults.py`'s curated console list) -- it does nothing itself, since the patched launch never reaches it, and it deliberately has no icon or other resources (a real icon was tried once, but broke every stub install on API 30+ system images -- see git history). iiSU's own package-visibility check doesn't need one either way. The Manager's Emulators page has an "Install Redirector Apps..." button that re-runs this any time (e.g. after adding a console's emulator by hand).

## Project layout

```
Setup.bat, Uninstall.bat   installer/ entry points (CLI-only shortcuts to setup_gui.py / uninstall.py)
VERSION                    this install's release tag, compared against GitHub Releases by updater.py on a non-git install

shared/theme.py            the dark/gradient look shared by every GUI in this project
shared/emulator_defaults.py  curated console -> PC emulator mappings, and which need a redirector
shared/avatars.py          fetches+circle-crops a GitHub avatar for the Credits page, with a no-Pillow/no-network fallback

installer/
  setup_wizard.py          first-time setup, called by setup_gui.py and usable from the CLI
  setup_gui.py             GUI front end for setup_wizard.py -- its own window, opened from the Manager's Home page
  sdk_bootstrap.py         downloads/installs the Android SDK and creates the AVD
  patch_iisu.py            decompiles, patches, rebuilds, and signs your iiSU APK
  smali_patch/             the injected LaunchBridge classes patch_iisu.py adds to iiSU
  stub_apk.py              builds/installs the placeholder "redirector" apps (see below)
  stub_apk_template/       the (identical, per-package-renamed) redirector app project
  uninstall.py             removes everything Setup.bat and day-to-day use create (see Uninstalling)

bridge/
  manager.py               the day-to-day app: Home (status/Start/Stop), all settings, Credits, Uninstall
  iiSU-PC Manager.bat       launches manager.py
  emulator_dialogs.py      the Add/Edit-mapping and Install-Redirector-Apps dialogs, shared by manager.py and onboarding_wizard.py
  onboarding_wizard.py     step-by-step first-run setup, launched automatically after Setup finishes
  bridge_config.py         shared config.json loader (used by everything below)
  apply_display.py         applies config.json's display settings to the AVD and cold-boots it
  start_iisu_pc.py         checks for updates, boots the AVD (if needed), and starts launch_bridge.py
  updater.py               checks for (and, on a git checkout, applies) updates before every start
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
- `bridge/emulator.log` has the Android emulator's own output if the VM won't boot; `bridge/bridge.log` has the launch bridge's (what it tried to launch and why, if a game doesn't redirect); `bridge/stop.log` has the shutdown-hotkey teardown's. None of these three show a console window of their own -- open the folder from the Manager's Home page (Logs button) to check them.
- Re-running setup is safe — it skips anything already done (SDK, AVD, keystore) and won't overwrite an existing `bridge/config.json`'s ROM directory/emulator settings.
- The AVD always cold-boots and never keeps a resume snapshot around (removed automatically after every clean Stop) — a resumed snapshot can carry forward storage/mount state that's since gone stale, so this trades a bit of boot time for not hitting that class of bug.

## Credits

- **[MAGOOSKEE](https://github.com/MAGOOSKEE)** -- project owner, built and maintains iiSU-PC.
- **[Claude](https://github.com/claude)** (Anthropic) -- AI coding assistant; wrote and refactored most of this codebase, including the Manager app, in collaboration with MAGOOSKEE.

Both are shown with live GitHub avatars on the Manager's own Credits page.

**AI disclosure:** a large share of this project's code was written by Claude, an AI assistant, working under MAGOOSKEE's direction and review -- not hand-written line by line by a human. If you're evaluating this project for safety or correctness before running it (it patches an APK and sets up a VM, both of which touch your system), keep that in mind and read the source rather than assuming a human wrote every line.
