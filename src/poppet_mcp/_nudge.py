"""Best-effort: nudge Cascadeur to run 'Commands -> Poppet -> Process Pending'.

Windows-only. Uses pure ctypes (no extra dependencies) to:
  1. Find Cascadeur's main window via EnumWindows + GetWindowThreadProcessId
  2. Foreground it via SetForegroundWindow / ShowWindow
  3. Send the keyboard sequence: Alt+C (Commands menu), 'p' (Poppet), 'p' (Process Pending)

If anything fails (Cascadeur not running, window not findable, simulated input blocked),
this returns silently. The user can always click the menu manually as a fallback.

This is intentionally fragile and best-effort. The CORRECT long-term fix is for
Cascadeur to expose a main-thread scheduling API; until then, this is the bridge.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


def try_nudge_cascadeur() -> bool:
    """Return True if we believe the nudge fired; False otherwise. Never raises."""
    if sys.platform != "win32":
        return False
    try:
        hwnd = _find_cascadeur_window()
        if hwnd is None:
            return False
        return _send_menu_sequence(hwnd)
    except Exception:
        return False


def _find_cascadeur_window() -> int | None:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    found: list[int] = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if "Cascadeur" in title:
            found.append(hwnd)
            return False  # stop enumeration
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return found[0] if found else None


def _send_menu_sequence(hwnd: int) -> bool:
    """Bring Cascadeur to front and send Alt+C, p, p (Commands -> Poppet -> Process Pending)."""
    user32 = ctypes.windll.user32

    # Windows focus-stealing prevention: SetForegroundWindow only succeeds when
    # the calling process owns focus, OR right after a key event has been
    # synthesized. Prime the queue with an Alt down/up, then it accepts.
    VK_MENU = 0x12
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, 0x0002, 0)  # KEYEVENTF_KEYUP

    # SW_RESTORE = 9
    user32.ShowWindow(hwnd, 9)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)  # ignore return — we primed, should work now

    # Tiny pause so the foreground change settles before keys go to it.
    import time
    time.sleep(0.1)

    # Verify Cascadeur is now foreground; abort if not (we'd type into the wrong app).
    if user32.GetForegroundWindow() != hwnd:
        return False

    KEYEVENTF_KEYUP = 0x0002
    VK_C = ord("C")
    VK_P = ord("P")
    VK_DOWN = 0x28
    VK_RETURN = 0x0D
    VK_MENU_KEY = 0x12  # Alt

    def down(vk: int):
        user32.keybd_event(vk, 0, 0, 0)

    def up(vk: int):
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

    def tap(vk: int):
        down(vk)
        up(vk)

    # Alt+C → opens Commands menu.
    down(VK_MENU_KEY)
    tap(VK_C)
    up(VK_MENU_KEY)
    time.sleep(0.08)

    # In the Commands menu, multiple items start with 'P' (Print mesh info, Poppet).
    # First 'p' highlights "Print mesh info", second 'p' cycles to "Poppet".
    tap(VK_P)
    time.sleep(0.04)
    tap(VK_P)
    time.sleep(0.04)
    # Enter opens the Poppet submenu.
    tap(VK_RETURN)
    time.sleep(0.08)
    # Process Pending is the first 'P' in the submenu (Process Pending, Refresh Schema).
    tap(VK_P)
    return True
