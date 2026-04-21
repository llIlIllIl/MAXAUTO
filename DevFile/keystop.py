import ctypes
from ctypes import wintypes
import time
import sys

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Windows constants
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
VK_ESCAPE = 0x1B
HC_ACTION = 0

# Structures
ULONG_PTR = wintypes.WPARAM


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]


# Function prototypes
LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    wintypes.LPARAM,  # LRESULT
    ctypes.c_int,     # nCode
    wintypes.WPARAM,  # wParam
    wintypes.LPARAM   # lParam
)

user32.SetWindowsHookExW.argtypes = (
    ctypes.c_int,
    LowLevelKeyboardProc,
    wintypes.HINSTANCE,
    wintypes.DWORD,
)
user32.SetWindowsHookExW.restype = wintypes.HHOOK

user32.CallNextHookEx.argtypes = (
    wintypes.HHOOK,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
user32.CallNextHookEx.restype = wintypes.LPARAM

user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
user32.UnhookWindowsHookEx.restype = wintypes.BOOL

user32.GetMessageW.argtypes = (
    ctypes.POINTER(MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
)
user32.GetMessageW.restype = wintypes.BOOL

user32.TranslateMessage.argtypes = (ctypes.POINTER(MSG),)
user32.TranslateMessage.restype = wintypes.BOOL

user32.DispatchMessageW.argtypes = (ctypes.POINTER(MSG),)
user32.DispatchMessageW.restype = wintypes.LPARAM

user32.PostQuitMessage.argtypes = (ctypes.c_int,)
user32.PostQuitMessage.restype = None

kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


# Global state
hook_id = None
hook_proc_ref = None
block_until = 0.0


def uninstall_hook():
    global hook_id
    if hook_id:
        user32.UnhookWindowsHookEx(hook_id)
        hook_id = None


@LowLevelKeyboardProc
def keyboard_proc(nCode, wParam, lParam):
    global block_until

    if nCode == HC_ACTION and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
        kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents

        now = time.time()
        if now < block_until and kb.vkCode == VK_ESCAPE:
            remaining = max(0.0, block_until - now)
            print(f"[BLOCKED] ESC ignored ({remaining:.1f}s left)")
            # Returning non-zero prevents the keystroke from being passed on
            return 1

        if now >= block_until:
            print("[INFO] Block time ended. Restoring ESC.")
            uninstall_hook()
            user32.PostQuitMessage(0)
            return user32.CallNextHookEx(None, nCode, wParam, lParam)

    return user32.CallNextHookEx(None, nCode, wParam, lParam)


def install_hook():
    global hook_id, hook_proc_ref
    hook_proc_ref = keyboard_proc  # keep reference alive
    h_instance = kernel32.GetModuleHandleW(None)

    hook_id = user32.SetWindowsHookExW(
        WH_KEYBOARD_LL,
        hook_proc_ref,
        h_instance,
        0
    )

    if not hook_id:
        raise ctypes.WinError(ctypes.get_last_error())


def run_message_loop():
    msg = MSG()
    while True:
        result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if result == 0:
            break
        if result == -1:
            raise ctypes.WinError(ctypes.get_last_error())
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def main():
    global block_until

    seconds = 10
    if len(sys.argv) >= 2:
        try:
            seconds = int(sys.argv[1])
        except ValueError:
            print("Usage: python block_esc.py [seconds]")
            return

    block_until = time.time() + seconds

    print(f"[INFO] ESC will be blocked globally for {seconds} seconds.")
    print("[INFO] Press other keys normally. ESC will be ignored during the block period.")
    print("[INFO] After the timer ends, the hook will be removed automatically.")

    try:
        install_hook()
        run_message_loop()
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user.")
    finally:
        uninstall_hook()
        print("[INFO] Hook removed. Program exiting.")


if __name__ == "__main__":
    main()
