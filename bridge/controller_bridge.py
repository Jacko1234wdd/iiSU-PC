"""
Automatic Xbox-compatible controller support for iiSU's own menu navigation.

Polls XInput (covers Xbox controllers whether wired USB or paired over
Bluetooth -- XInput doesn't care about transport) and forwards button
presses into the AVD as Android KeyEvents via a persistent `adb shell`
session, so plugging in or pairing a controller "just works" with no
manual configuration and no USB passthrough / driver swapping.

Scope: XInput only. PlayStation-style controllers (DualShock/DualSense)
enumerate as DirectInput/HID on Windows, not XInput, unless something like
Steam Input or DS4Windows remaps them to XInput -- those aren't covered
here.

Only forwards input while iiSU itself is what you'd be looking at (no game
currently running via the bridge); once a game launches, the real PC
emulator reads the same physical controller directly through Windows
(XInput polling isn't exclusive, so this doesn't conflict with it), so
there's nothing useful for this to send until you're back at iiSU.
"""

import ctypes
import subprocess
import time

# XINPUT_GAMEPAD.wButtons bitmask
XINPUT_GAMEPAD_DPAD_UP = 0x0001
XINPUT_GAMEPAD_DPAD_DOWN = 0x0002
XINPUT_GAMEPAD_DPAD_LEFT = 0x0004
XINPUT_GAMEPAD_DPAD_RIGHT = 0x0008
XINPUT_GAMEPAD_START = 0x0010
XINPUT_GAMEPAD_BACK = 0x0020
XINPUT_GAMEPAD_LEFT_THUMB = 0x0040
XINPUT_GAMEPAD_RIGHT_THUMB = 0x0080
XINPUT_GAMEPAD_LEFT_SHOULDER = 0x0100
XINPUT_GAMEPAD_RIGHT_SHOULDER = 0x0200
XINPUT_GAMEPAD_A = 0x1000
XINPUT_GAMEPAD_B = 0x2000
XINPUT_GAMEPAD_X = 0x4000
XINPUT_GAMEPAD_Y = 0x8000

ERROR_SUCCESS = 0

# Android KeyEvent codes -- iiSU listens to these directly (confirmed by its
# own on-screen "A Select / B Back / LB RB ..." gamepad legends).
BUTTON_TO_KEYCODE = {
    XINPUT_GAMEPAD_DPAD_UP: 19,
    XINPUT_GAMEPAD_DPAD_DOWN: 20,
    XINPUT_GAMEPAD_DPAD_LEFT: 21,
    XINPUT_GAMEPAD_DPAD_RIGHT: 22,
    XINPUT_GAMEPAD_A: 96,
    XINPUT_GAMEPAD_B: 97,
    XINPUT_GAMEPAD_X: 99,
    XINPUT_GAMEPAD_Y: 100,
    XINPUT_GAMEPAD_LEFT_SHOULDER: 102,
    XINPUT_GAMEPAD_RIGHT_SHOULDER: 103,
    XINPUT_GAMEPAD_LEFT_THUMB: 106,
    XINPUT_GAMEPAD_RIGHT_THUMB: 107,
    XINPUT_GAMEPAD_START: 108,
    XINPUT_GAMEPAD_BACK: 109,
}
KEYCODE_BUTTON_L2 = 104
KEYCODE_BUTTON_R2 = 105
KEYCODE_DPAD_UP, KEYCODE_DPAD_DOWN, KEYCODE_DPAD_LEFT, KEYCODE_DPAD_RIGHT = 19, 20, 21, 22

REPEATABLE = {KEYCODE_DPAD_UP, KEYCODE_DPAD_DOWN, KEYCODE_DPAD_LEFT, KEYCODE_DPAD_RIGHT}
INITIAL_REPEAT_DELAY = 0.4
REPEAT_INTERVAL = 0.12
TRIGGER_THRESHOLD = 128
STICK_DEADZONE = 12000
POLL_HZ = 60


class XinputGamepad(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_ushort),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class XinputState(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_uint32), ("Gamepad", XinputGamepad)]


def _load_xinput():
    for name in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"):
        try:
            return ctypes.windll.LoadLibrary(name)
        except OSError:
            continue
    return None


_xinput = _load_xinput()
if _xinput is not None:
    _xinput.XInputGetState.argtypes = [ctypes.c_uint32, ctypes.POINTER(XinputState)]
    _xinput.XInputGetState.restype = ctypes.c_uint32


def get_gamepad_state(slot: int) -> XinputGamepad | None:
    if _xinput is None:
        return None
    state = XinputState()
    if _xinput.XInputGetState(slot, ctypes.byref(state)) == ERROR_SUCCESS:
        return state.Gamepad
    return None


class ControllerBridge:
    """is_game_running: zero-arg callable returning True while a real PC
    emulator is active, so this pauses instead of fighting for input."""

    def __init__(self, is_game_running):
        self.is_game_running = is_game_running
        self._adb_shell: subprocess.Popen | None = None
        self._connected_slots: set[int] = set()
        self._held_since: dict[tuple[int, int], float] = {}
        self._last_repeat: dict[tuple[int, int], float] = {}

    def _ensure_shell(self) -> None:
        if self._adb_shell is None or self._adb_shell.poll() is not None:
            self._adb_shell = subprocess.Popen(
                ["adb", "shell"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def _send_keyevent(self, code: int) -> None:
        self._ensure_shell()
        try:
            self._adb_shell.stdin.write(f"input keyevent {code}\n".encode())
            self._adb_shell.stdin.flush()
        except (BrokenPipeError, OSError):
            self._adb_shell = None

    @staticmethod
    def _digital_buttons(pad: XinputGamepad) -> set[int]:
        pressed = {code for bit, code in BUTTON_TO_KEYCODE.items() if pad.wButtons & bit}
        if pad.bLeftTrigger > TRIGGER_THRESHOLD:
            pressed.add(KEYCODE_BUTTON_L2)
        if pad.bRightTrigger > TRIGGER_THRESHOLD:
            pressed.add(KEYCODE_BUTTON_R2)
        # Thumbsticks double as D-pad for menu navigation, past a deadzone.
        if pad.sThumbLY > STICK_DEADZONE or pad.sThumbRY > STICK_DEADZONE:
            pressed.add(KEYCODE_DPAD_UP)
        if pad.sThumbLY < -STICK_DEADZONE or pad.sThumbRY < -STICK_DEADZONE:
            pressed.add(KEYCODE_DPAD_DOWN)
        if pad.sThumbLX < -STICK_DEADZONE or pad.sThumbRX < -STICK_DEADZONE:
            pressed.add(KEYCODE_DPAD_LEFT)
        if pad.sThumbLX > STICK_DEADZONE or pad.sThumbRX > STICK_DEADZONE:
            pressed.add(KEYCODE_DPAD_RIGHT)
        return pressed

    def _poll_slot(self, slot: int, now: float) -> None:
        pad = get_gamepad_state(slot)
        if pad is None:
            if slot in self._connected_slots:
                print(f"[controller] slot {slot} disconnected")
                self._connected_slots.discard(slot)
            return
        if slot not in self._connected_slots:
            print(f"[controller] slot {slot} connected (wired or Bluetooth, detected automatically)")
            self._connected_slots.add(slot)

        pressed = self._digital_buttons(pad)

        for key in [k for k in self._held_since if k[0] == slot and k[1] not in pressed]:
            del self._held_since[key]
            self._last_repeat.pop(key, None)

        for code in pressed:
            key = (slot, code)
            if key not in self._held_since:
                self._held_since[key] = now
                self._send_keyevent(code)
            elif code in REPEATABLE:
                held_for = now - self._held_since[key]
                last = self._last_repeat.get(key, self._held_since[key])
                if held_for >= INITIAL_REPEAT_DELAY and now - last >= REPEAT_INTERVAL:
                    self._send_keyevent(code)
                    self._last_repeat[key] = now

    def run(self) -> None:
        if _xinput is None:
            print("[controller] XInput not available on this system; controller support disabled")
            return
        print("[controller] watching for Xbox-compatible controllers (wired or Bluetooth)")
        while True:
            if not self.is_game_running():
                now = time.time()
                for slot in range(4):
                    self._poll_slot(slot, now)
            time.sleep(1 / POLL_HZ)
