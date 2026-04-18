from __future__ import annotations

import ctypes
import sys
from typing import Any


def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def get_monitor_refresh_rate(widget: Any | None = None, default: int = 60) -> int:
    if sys.platform != "win32":
        return default
    try:
        x, y = _widget_center(widget)
        return _win32_refresh_rate_at_point(x, y, default)
    except Exception:
        return default


def monitor_frame_interval_ms(widget: Any | None = None, default_refresh_rate: int = 60) -> int:
    refresh_rate = max(1, get_monitor_refresh_rate(widget, default_refresh_rate))
    return max(1, round(1000 / refresh_rate))


def _widget_center(widget: Any | None) -> tuple[int, int]:
    if widget is None:
        return 0, 0
    try:
        widget.update_idletasks()
        width = max(1, int(widget.winfo_width()))
        height = max(1, int(widget.winfo_height()))
        return int(widget.winfo_rootx()) + width // 2, int(widget.winfo_rooty()) + height // 2
    except Exception:
        return 0, 0


def _win32_refresh_rate_at_point(x: int, y: int, default: int) -> int:
    user32 = ctypes.windll.user32
    ENUM_CURRENT_SETTINGS = -1
    MONITOR_DEFAULTTONEAREST = 2
    CCHDEVICENAME = 32
    CCHFORMNAME = 32

    class POINT(ctypes.Structure):
        _fields_ = [
            ("x", ctypes.c_long),
            ("y", ctypes.c_long),
        ]

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", ctypes.c_ulong),
            ("szDevice", ctypes.c_wchar * CCHDEVICENAME),
        ]

    class DEVMODEW(ctypes.Structure):
        _fields_ = [
            ("dmDeviceName", ctypes.c_wchar * CCHDEVICENAME),
            ("dmSpecVersion", ctypes.c_ushort),
            ("dmDriverVersion", ctypes.c_ushort),
            ("dmSize", ctypes.c_ushort),
            ("dmDriverExtra", ctypes.c_ushort),
            ("dmFields", ctypes.c_ulong),
            ("dmOrientation", ctypes.c_short),
            ("dmPaperSize", ctypes.c_short),
            ("dmPaperLength", ctypes.c_short),
            ("dmPaperWidth", ctypes.c_short),
            ("dmScale", ctypes.c_short),
            ("dmCopies", ctypes.c_short),
            ("dmDefaultSource", ctypes.c_short),
            ("dmPrintQuality", ctypes.c_short),
            ("dmColor", ctypes.c_short),
            ("dmDuplex", ctypes.c_short),
            ("dmYResolution", ctypes.c_short),
            ("dmTTOption", ctypes.c_short),
            ("dmCollate", ctypes.c_short),
            ("dmFormName", ctypes.c_wchar * CCHFORMNAME),
            ("dmLogPixels", ctypes.c_ushort),
            ("dmBitsPerPel", ctypes.c_ulong),
            ("dmPelsWidth", ctypes.c_ulong),
            ("dmPelsHeight", ctypes.c_ulong),
            ("dmDisplayFlags", ctypes.c_ulong),
            ("dmDisplayFrequency", ctypes.c_ulong),
        ]

    user32.MonitorFromPoint.argtypes = [POINT, ctypes.c_ulong]
    user32.MonitorFromPoint.restype = ctypes.c_void_p
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFOEXW)]
    user32.GetMonitorInfoW.restype = ctypes.c_int
    user32.EnumDisplaySettingsW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.POINTER(DEVMODEW)]
    user32.EnumDisplaySettingsW.restype = ctypes.c_int

    monitor = user32.MonitorFromPoint(POINT(x, y), MONITOR_DEFAULTTONEAREST)
    if not monitor:
        return default

    info = MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(MONITORINFOEXW)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return default

    devmode = DEVMODEW()
    devmode.dmSize = ctypes.sizeof(DEVMODEW)
    if not user32.EnumDisplaySettingsW(info.szDevice, ENUM_CURRENT_SETTINGS, ctypes.byref(devmode)):
        return default

    refresh_rate = int(devmode.dmDisplayFrequency)
    if refresh_rate <= 1 or refresh_rate > 1000:
        return default
    return refresh_rate
