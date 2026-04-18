from __future__ import annotations

import ctypes
import queue
import sys
import threading
import time
from ctypes import wintypes
from typing import Any


class KbdLlHookStruct(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class GlobalEnterListener(threading.Thread):
    WH_KEYBOARD_LL = 13
    HC_ACTION = 0
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104
    WM_QUIT = 0x0012
    VK_RETURN = 0x0D
    VK_INSERT = 0x2D
    VK_DELETE = 0x2E
    VK_OEM_PLUS = 0xBB

    def __init__(self, event_queue: queue.Queue[dict[str, Any]]) -> None:
        super().__init__(daemon=True)
        self.event_queue = event_queue
        self.stop_event = threading.Event()
        self.thread_id: int | None = None
        self.hook_handle: int | None = None
        self._callback: Any = None
        self._last_emit = 0.0

    def stop(self) -> None:
        self.stop_event.set()
        if sys.platform == "win32" and self.thread_id is not None:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, self.WM_QUIT, 0, 0)

    def run(self) -> None:
        if sys.platform != "win32":
            self.event_queue.put({"type": "global_enter_error", "message": "전역 Enter는 Windows에서만 지원됩니다."})
            return

        try:
            self._run_windows_hook()
        except Exception as exc:
            self.event_queue.put({"type": "global_enter_error", "message": str(exc)})

    def _run_windows_hook(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        lresult_type = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)
        hook_proc_type = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
            lresult_type,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )

        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, hook_proc_type, ctypes.c_void_p, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = lresult_type
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        def hook_proc(n_code: int, w_param: int, l_param: int) -> int:
            if n_code == self.HC_ACTION and w_param in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN):
                event = ctypes.cast(l_param, ctypes.POINTER(KbdLlHookStruct)).contents
                if event.vkCode in (self.VK_RETURN, self.VK_INSERT, self.VK_DELETE, self.VK_OEM_PLUS):
                    now = time.monotonic()
                    if now - self._last_emit >= 0.2:
                        self._last_emit = now
                        if event.vkCode == self.VK_RETURN:
                            self.event_queue.put({"type": "resume_requested", "source": "global_enter"})
                        elif event.vkCode == self.VK_DELETE:
                            self.event_queue.put({"type": "delete_requested", "source": "global_delete"})
                        elif event.vkCode == self.VK_INSERT:
                            self.event_queue.put({"type": "insert_requested", "source": "global_insert"})
                        else:
                            self.event_queue.put({"type": "manual_overlay_requested", "source": "global_equal"})
            return user32.CallNextHookEx(self.hook_handle, n_code, w_param, l_param)

        self.thread_id = int(kernel32.GetCurrentThreadId())
        self._callback = hook_proc_type(hook_proc)
        module_handle = kernel32.GetModuleHandleW(None)
        self.hook_handle = user32.SetWindowsHookExW(self.WH_KEYBOARD_LL, self._callback, module_handle, 0)
        if not self.hook_handle:
            raise ctypes.WinError(ctypes.get_last_error())

        self.event_queue.put({"type": "global_enter_ready", "message": "백그라운드 Enter 활성화"})
        msg = wintypes.MSG()
        try:
            while not self.stop_event.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == 0 or result == -1:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self.hook_handle:
                user32.UnhookWindowsHookEx(self.hook_handle)
                self.hook_handle = None
