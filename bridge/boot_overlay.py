"""
A fullscreen black overlay covering the primary monitor, shown during the
two moments this project's own windows would otherwise leave raw desktop
visible behind them:
  - while the AVD cold-boots (its window exists but isn't fullscreened
    yet until launch_bridge.py's show_iisu_window() runs, well after the
    process itself starts)
  - while a game hands off from iiSU to a real PC emulator (between
    iiSU's window minimizing and the emulator's own window appearing and
    taking the foreground)

Implemented as a short-lived PowerShell + WinForms process rather than a
second Tk window, since both callers here need to work regardless of
which thread calls them -- start_iisu_pc.py directly (its own process,
any thread), and launch_bridge.py, which itself sometimes runs from a
background thread of manager.py's own long-lived Tk app. Tcl/Tk's global
state isn't built for a second Tk root from a thread that isn't already
running the existing one's mainloop; a wholly separate OS process
sidesteps that class of problem entirely.
"""

import subprocess

_OVERLAY_SCRIPT = r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$form = New-Object System.Windows.Forms.Form
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
# WindowState=Maximized on a borderless form is unreliable (a known
# WinForms quirk -- it can maximize against stale/default bounds instead
# of the real screen), so this sets the exact screen rectangle directly
# instead of asking the form to guess it.
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual
$form.Location = New-Object System.Drawing.Point($bounds.X, $bounds.Y)
$form.Size = New-Object System.Drawing.Size($bounds.Width, $bounds.Height)
$form.TopMost = $true
$form.BackColor = [System.Drawing.Color]::Black
$form.Cursor = [System.Windows.Forms.Cursors]::None
$label = New-Object System.Windows.Forms.Label
$label.Text = "iiSU-PC"
$label.ForeColor = [System.Drawing.Color]::FromArgb(90, 90, 96)
$label.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 20)
$label.Dock = [System.Windows.Forms.DockStyle]::Fill
$label.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
$form.Controls.Add($label)
$form.Add_Shown({ $form.Activate() })
[System.Windows.Forms.Application]::Run($form)
"""


def show() -> subprocess.Popen | None:
    """Best-effort: returns None instead of raising if PowerShell/WinForms
    aren't available for any reason -- a missing overlay is a cosmetic
    regression, never a reason to fail an actual start or game launch."""
    try:
        return subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", _OVERLAY_SCRIPT],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None


def close(overlay: subprocess.Popen | None) -> None:
    """Forcibly kills the overlay process rather than trying to close its
    window gracefully -- it has no state to lose and no user input to
    flush, so instant is strictly better here than any delay."""
    if overlay is None:
        return
    try:
        overlay.terminate()
    except OSError:
        pass
