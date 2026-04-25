from __future__ import annotations

import ctypes
import sys
from typing import Any

import tkinter as tk
from tkinter import ttk

from .system import monitor_frame_interval_ms


def _target_monitor_rect(root: tk.Tk) -> tuple[int, int, int, int]:
    if sys.platform != "win32":
        return (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())

    try:
        user32 = ctypes.windll.user32
        MONITOR_DEFAULTTONEAREST = 2

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_ulong),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", ctypes.c_ulong),
            ]

        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        user32.MonitorFromWindow.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
        user32.GetMonitorInfoW.restype = ctypes.c_int

        hwnd = user32.GetForegroundWindow()
        monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if not monitor:
            raise RuntimeError("No monitor for foreground window.")
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            raise RuntimeError("GetMonitorInfoW failed.")
        rect = info.rcMonitor
        return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    except Exception:
        return (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())


def _apply_win32_overlay_styles(window: tk.Toplevel, click_through: bool, focus_safe: bool) -> bool:
    if sys.platform != "win32":
        return False

    try:
        user32 = ctypes.windll.user32
        hwnd = ctypes.c_void_p(int(window.winfo_id()))
        GWL_EXSTYLE = -20
        WS_EX_TOPMOST = 0x00000008
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_LAYERED = 0x00080000
        WS_EX_NOACTIVATE = 0x08000000
        LWA_ALPHA = 0x00000002
        HWND_TOPMOST = ctypes.c_void_p(-1)
        SW_SHOWNOACTIVATE = 4
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOOWNERZORDER = 0x0200
        SWP_SHOWWINDOW = 0x0040
        SWP_NOACTIVATE = 0x0010

        user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
        user32.SetWindowLongW.restype = ctypes.c_long
        user32.SetLayeredWindowAttributes.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ubyte,
            ctypes.c_ulong,
        ]
        user32.SetLayeredWindowAttributes.restype = ctypes.c_int
        user32.SetWindowPos.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = ctypes.c_int
        user32.ShowWindowAsync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.ShowWindowAsync.restype = ctypes.c_int

        style = int(user32.GetWindowLongW(hwnd, GWL_EXSTYLE))
        style |= WS_EX_TOPMOST | WS_EX_LAYERED | WS_EX_TOOLWINDOW
        if click_through:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        if focus_safe:
            style |= WS_EX_NOACTIVATE
        else:
            style &= ~WS_EX_NOACTIVATE
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
        user32.ShowWindowAsync(hwnd, SW_SHOWNOACTIVATE)

        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOOWNERZORDER | SWP_SHOWWINDOW
        if focus_safe:
            flags |= SWP_NOACTIVATE
        return bool(user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags))
    except Exception:
        return False


class _ExclusiveTopmostKeeper:
    topmost_keepalive_ms = 250

    def _has_existing_overlay_window(self) -> bool:
        window = getattr(self, "window", None)
        if window is None:
            return False
        try:
            return bool(window.winfo_exists())
        except tk.TclError:
            return False

    def _reapply_exclusive_topmost(self) -> bool:
        if not getattr(self, "exclusive_compat", False):
            return False
        window = getattr(self, "window", None)
        if window is None or not self._has_existing_overlay_window():
            return False
        return _apply_win32_overlay_styles(
            window,
            bool(getattr(self, "click_through", False)),
            bool(getattr(self, "focus_safe", True)),
        )

    def _start_topmost_keepalive(self) -> None:
        if not getattr(self, "exclusive_compat", False):
            return
        if getattr(self, "topmost_job", None) is not None:
            return
        self._reapply_exclusive_topmost()
        self.topmost_job = self.root.after(self.topmost_keepalive_ms, self._topmost_keepalive_tick)

    def _topmost_keepalive_tick(self) -> None:
        self.topmost_job = None
        if not getattr(self, "exclusive_compat", False) or not self._has_existing_overlay_window():
            return
        self._reapply_exclusive_topmost()
        self.topmost_job = self.root.after(self.topmost_keepalive_ms, self._topmost_keepalive_tick)

    def _cancel_topmost_keepalive(self) -> None:
        job = getattr(self, "topmost_job", None)
        if job is None:
            return
        try:
            self.root.after_cancel(job)
        except tk.TclError:
            pass
        self.topmost_job = None


class RegistrationOverlay(_ExclusiveTopmostKeeper):
    def __init__(
        self,
        root: tk.Tk,
        heading: str,
        result_difficult: str,
        result_button: str,
        result_title: str,
        result_score: str,
        result_score_color: str,
        result_suffix: str,
        footer: str,
        duration_seconds: int,
        on_accept: Any,
        on_cancel: Any,
        on_retry: Any,
        on_manual: Any,
        exclusive_compat: bool = False,
        click_through: bool = False,
        focus_safe: bool = True,
    ) -> None:
        self.root = root
        self.heading = heading
        self.result_difficult = result_difficult
        self.result_button = result_button
        self.result_title = result_title
        self.result_score = result_score
        self.result_score_color = result_score_color
        self.result_suffix = result_suffix
        self.footer = footer
        self.duration_seconds = max(1, int(duration_seconds))
        self.on_accept = on_accept
        self.on_cancel = on_cancel
        self.on_retry = on_retry
        self.on_manual = on_manual
        self.exclusive_compat = exclusive_compat
        self.click_through = click_through
        self.focus_safe = focus_safe
        self.window: tk.Toplevel | None = None
        self.progress_canvas: tk.Canvas | None = None
        self.finished = False
        self.cancelled = False
        self.elapsed_ms = 0
        self.timer_job: str | None = None
        self.animation_job: str | None = None
        self.topmost_job: str | None = None

        self.width = 520
        self.height = 150
        self.margin_top = 28
        self.margin_right = 28
        self.progress_column_width = 60
        self.animation_ms = 360
        self.frame_interval_ms = monitor_frame_interval_ms(root)
        self.timer_interval_ms = self.frame_interval_ms

    def show(self) -> None:
        self.window = tk.Toplevel(self.root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg="#111820")

        frame = tk.Frame(self.window, bg="#111820", padx=18, pady=16)
        frame.pack(fill=tk.BOTH, expand=True)

        progress_column = tk.Frame(frame, width=self.progress_column_width, bg="#111820")
        progress_column.pack(side=tk.LEFT, fill=tk.Y)
        progress_column.pack_propagate(False)
        self.progress_canvas = tk.Canvas(progress_column, width=46, height=46, bg="#111820", highlightthickness=0)
        self.progress_canvas.place(relx=0.0, rely=0.5, anchor="w")

        content = tk.Frame(frame, bg="#111820")
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        heading_label = tk.Label(
            content,
            text=self.heading,
            justify=tk.RIGHT,
            anchor="e",
            bg="#111820",
            fg="white",
            font=("Malgun Gothic", 12),
        )
        heading_label.pack(fill=tk.X, anchor="e")

        result_row = tk.Frame(content, bg="#111820")
        result_row.pack(anchor="e", pady=(2, 4))
        tk.Label(
            result_row,
            text=f"[{self.result_difficult} - {self.result_button}] {self.result_title} - ",
            bg="#111820",
            fg="white",
            font=("Malgun Gothic", 17, "bold"),
        ).pack(side=tk.LEFT)
        tk.Label(
            result_row,
            text=self.result_score,
            bg="#111820",
            fg=self.result_score_color,
            font=("Malgun Gothic", 17, "bold"),
        ).pack(side=tk.LEFT)
        if self.result_suffix:
            tk.Label(
                result_row,
                text=f" {self.result_suffix}",
                bg="#111820",
                fg=self.result_score_color,
                font=("Malgun Gothic", 17, "bold"),
            ).pack(side=tk.LEFT)

        footer_label = tk.Label(
            content,
            text=self.footer,
            justify=tk.RIGHT,
            anchor="e",
            bg="#111820",
            fg="white",
            font=("Malgun Gothic", 12),
        )
        footer_label.pack(fill=tk.X, anchor="e")

        button_row = tk.Frame(content, bg="#111820")
        button_row.pack(fill=tk.X, pady=(8, 0))
        delete_button = tk.Button(
            button_row,
            text="Delete",
            command=self.cancel,
            bg="#8a1f1f",
            fg="white",
            activebackground="#b72a2a",
            activeforeground="white",
            relief=tk.FLAT,
            padx=14,
            pady=4,
            anchor="e",
        )
        delete_button.pack(side=tk.RIGHT)
        insert_button = tk.Button(
            button_row,
            text="Insert",
            command=self.retry,
            bg="#1f5f8a",
            fg="white",
            activebackground="#2c78ad",
            activeforeground="white",
            relief=tk.FLAT,
            padx=14,
            pady=4,
            anchor="e",
        )
        insert_button.pack(side=tk.RIGHT, padx=(0, 8))
        manual_button = tk.Button(
            button_row,
            text="=",
            command=self.manual,
            bg="#3b4252",
            fg="white",
            activebackground="#4c566a",
            activeforeground="white",
            relief=tk.FLAT,
            padx=14,
            pady=4,
            anchor="e",
        )
        manual_button.pack(side=tk.RIGHT, padx=(0, 8))

        monitor_left, monitor_top, monitor_right, monitor_bottom = _target_monitor_rect(self.root)
        monitor_w = max(1, monitor_right - monitor_left)
        self.window.update_idletasks()
        self.width = min(max(self.width, self.window.winfo_reqwidth()), max(320, monitor_w - (self.margin_right * 2)))
        self.height = max(self.height, self.window.winfo_reqheight())
        self.visible_x = monitor_right - self.width - self.margin_right
        self.hidden_x = monitor_right + 24
        self.y = monitor_top + self.margin_top
        self.window.geometry(f"{self.width}x{self.height}+{self.hidden_x}+{self.y}")
        if self.exclusive_compat:
            self._reapply_exclusive_topmost()
        self.window.deiconify()
        if self.exclusive_compat:
            self._reapply_exclusive_topmost()
            self._start_topmost_keepalive()
        self._draw_progress(0.0)
        self._slide_to(self.hidden_x, self.visible_x, self.animation_ms, after=self._start_timer)

    def accept(self) -> None:
        self._finish(cancelled=False)

    def cancel(self) -> None:
        self._finish(cancelled=True)

    def retry(self) -> None:
        if self.finished:
            return
        self.finished = True
        self._cancel_jobs()
        current_x = self.visible_x
        if self.window is not None and self.window.winfo_exists():
            current_x = self.window.winfo_x()
        self._slide_to(current_x, self.hidden_x, self.animation_ms, after=lambda: self._destroy_and_callback(self.on_retry))

    def manual(self) -> None:
        if self.finished:
            return
        self.finished = True
        self._cancel_jobs()
        if self.window is not None and self.window.winfo_exists():
            self.window.destroy()
        self.root.after(0, self.on_manual)

    def close_now(self) -> None:
        self.finished = True
        self._cancel_jobs()
        if self.window is not None and self.window.winfo_exists():
            self.window.destroy()

    def _start_timer(self) -> None:
        self.elapsed_ms = 0
        self._tick()

    def _tick(self) -> None:
        if self.finished:
            return
        self.elapsed_ms += self.timer_interval_ms
        progress = min(1.0, self.elapsed_ms / (self.duration_seconds * 1000))
        self._draw_progress(progress)
        if progress >= 1.0:
            self.accept()
            return
        self.timer_job = self.root.after(self.timer_interval_ms, self._tick)

    def _finish(self, cancelled: bool) -> None:
        if self.finished:
            return
        self.finished = True
        self.cancelled = cancelled
        self._cancel_jobs()
        current_x = self.visible_x
        if self.window is not None and self.window.winfo_exists():
            current_x = self.window.winfo_x()
        callback = self.on_cancel if cancelled else self.on_accept
        self._slide_to(current_x, self.hidden_x, self.animation_ms, after=lambda: self._destroy_and_callback(callback))

    def _destroy_and_callback(self, callback: Any) -> None:
        if self.window is not None and self.window.winfo_exists():
            self.window.destroy()
        self.root.after(0, callback)

    def _cancel_jobs(self) -> None:
        self._cancel_topmost_keepalive()
        for job in (self.timer_job, self.animation_job):
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except tk.TclError:
                    pass
        self.timer_job = None
        self.animation_job = None

    def _slide_to(self, start_x: int, end_x: int, duration_ms: int, after: Any | None = None) -> None:
        frame_interval = max(1, self.frame_interval_ms)
        frames = max(1, round(duration_ms / frame_interval))
        step_ms = max(1, round(duration_ms / frames))

        def animate(frame: int = 0) -> None:
            if self.window is None or not self.window.winfo_exists():
                return
            t = frame / frames
            eased = 1 - (1 - t) ** 3
            x = int(start_x + (end_x - start_x) * eased)
            self.window.geometry(f"{self.width}x{self.height}+{x}+{self.y}")
            self._reapply_exclusive_topmost()
            if frame >= frames:
                if after is not None:
                    after()
                return
            self.animation_job = self.root.after(step_ms, lambda: animate(frame + 1))

        animate()

    def _draw_progress(self, progress: float) -> None:
        if self.progress_canvas is None:
            return
        self.progress_canvas.delete("all")
        self.progress_canvas.create_oval(5, 5, 41, 41, outline="#5f6975", width=4)
        self.progress_canvas.create_arc(
            5,
            5,
            41,
            41,
            start=90,
            extent=-359.9 * max(0.0, min(1.0, progress)),
            outline="#ffffff",
            width=4,
            style=tk.ARC,
        )


class MessageOverlay(_ExclusiveTopmostKeeper):
    def __init__(
        self,
        root: tk.Tk,
        message: str,
        duration_seconds: int,
        on_close: Any,
        exclusive_compat: bool = False,
        click_through: bool = False,
        focus_safe: bool = True,
    ) -> None:
        self.root = root
        self.message = message
        self.duration_seconds = max(1, int(duration_seconds))
        self.on_close = on_close
        self.exclusive_compat = exclusive_compat
        self.click_through = click_through
        self.focus_safe = focus_safe
        self.window: tk.Toplevel | None = None
        self.progress_canvas: tk.Canvas | None = None
        self.timer_job: str | None = None
        self.animation_job: str | None = None
        self.topmost_job: str | None = None
        self.closed = False
        self.elapsed_ms = 0
        self.width = 520
        self.height = 96
        self.margin_top = 28
        self.margin_right = 28
        self.progress_column_width = 60
        self.animation_ms = 360
        self.frame_interval_ms = monitor_frame_interval_ms(root)
        self.timer_interval_ms = self.frame_interval_ms

    def show(self) -> None:
        self.window = tk.Toplevel(self.root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg="#111820")

        frame = tk.Frame(self.window, bg="#111820", padx=18, pady=16)
        frame.pack(fill=tk.BOTH, expand=True)

        progress_column = tk.Frame(frame, width=self.progress_column_width, bg="#111820")
        progress_column.pack(side=tk.LEFT, fill=tk.Y)
        progress_column.pack_propagate(False)
        self.progress_canvas = tk.Canvas(progress_column, width=46, height=46, bg="#111820", highlightthickness=0)
        self.progress_canvas.place(relx=0.0, rely=0.5, anchor="w")

        content = tk.Frame(frame, bg="#111820")
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Label(
            content,
            text=self.message,
            justify=tk.RIGHT,
            anchor="e",
            bg="#111820",
            fg="white",
            font=("Malgun Gothic", 14, "bold"),
        ).pack(fill=tk.BOTH, expand=True)

        monitor_left, monitor_top, monitor_right, monitor_bottom = _target_monitor_rect(self.root)
        monitor_w = max(1, monitor_right - monitor_left)
        self.window.update_idletasks()
        self.width = min(max(self.width, self.window.winfo_reqwidth()), max(320, monitor_w - (self.margin_right * 2)))
        self.height = max(self.height, self.window.winfo_reqheight())
        self.visible_x = monitor_right - self.width - self.margin_right
        self.hidden_x = monitor_right + 24
        self.y = monitor_top + self.margin_top
        self.window.geometry(f"{self.width}x{self.height}+{self.hidden_x}+{self.y}")
        if self.exclusive_compat:
            self._reapply_exclusive_topmost()
        self.window.deiconify()
        if self.exclusive_compat:
            self._reapply_exclusive_topmost()
            self._start_topmost_keepalive()
        self._draw_progress(0.0)
        self._slide_to(self.hidden_x, self.visible_x, self.animation_ms, after=self._start_timer)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._cancel_jobs()
        current_x = getattr(self, "visible_x", self.root.winfo_screenwidth())
        if self.window is not None and self.window.winfo_exists():
            current_x = self.window.winfo_x()
            self._slide_to(
                current_x,
                getattr(self, "hidden_x", self.root.winfo_screenwidth() + 24),
                self.animation_ms,
                after=self._destroy_and_callback,
            )
            return
        self.root.after(0, self.on_close)

    def _destroy_and_callback(self) -> None:
        if self.window is not None and self.window.winfo_exists():
            self.window.destroy()
        self.root.after(0, self.on_close)

    def close_now(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._cancel_jobs()
        if self.window is not None and self.window.winfo_exists():
            self.window.destroy()

    def _start_timer(self) -> None:
        self.elapsed_ms = 0
        self._tick()

    def _tick(self) -> None:
        if self.closed:
            return
        self.elapsed_ms += self.timer_interval_ms
        progress = min(1.0, self.elapsed_ms / (self.duration_seconds * 1000))
        self._draw_progress(progress)
        if progress >= 1.0:
            self.close()
            return
        self.timer_job = self.root.after(self.timer_interval_ms, self._tick)

    def _cancel_jobs(self) -> None:
        self._cancel_topmost_keepalive()
        for job in (self.timer_job, self.animation_job):
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except tk.TclError:
                    pass
        self.timer_job = None
        self.animation_job = None

    def _slide_to(self, start_x: int, end_x: int, duration_ms: int, after: Any | None = None) -> None:
        frame_interval = max(1, self.frame_interval_ms)
        frames = max(1, round(duration_ms / frame_interval))
        step_ms = max(1, round(duration_ms / frames))

        def animate(frame: int = 0) -> None:
            if self.window is None or not self.window.winfo_exists():
                return
            t = frame / frames
            eased = 1 - (1 - t) ** 3
            x = int(start_x + (end_x - start_x) * eased)
            self.window.geometry(f"{self.width}x{self.height}+{x}+{self.y}")
            self._reapply_exclusive_topmost()
            if frame >= frames:
                if after is not None:
                    after()
                return
            self.animation_job = self.root.after(step_ms, lambda: animate(frame + 1))

        animate()

    def _draw_progress(self, progress: float) -> None:
        if self.progress_canvas is None:
            return
        self.progress_canvas.delete("all")
        self.progress_canvas.create_oval(5, 5, 41, 41, outline="#5f6975", width=4)
        self.progress_canvas.create_arc(
            5,
            5,
            41,
            41,
            start=90,
            extent=-359.9 * max(0.0, min(1.0, progress)),
            outline="#ffffff",
            width=4,
            style=tk.ARC,
        )


class ManualOverlayInputDialog:
    def __init__(self, root: tk.Tk, title: str, score: str, break_value: str) -> None:
        self.root = root
        self.initial_values = {
            "Title": "" if title == "-" else title,
            "Score": "" if score == "-" else score,
            "BREAK": "" if break_value == "-" else break_value,
        }
        self.window: tk.Toplevel | None = None
        self.entries: dict[str, ttk.Entry] = {}
        self.result: dict[str, str] | None = None

    def show(self) -> dict[str, str] | None:
        self.window = tk.Toplevel(self.root)
        self.window.title("수동 입력")
        self.window.transient(self.root)
        self.window.attributes("-topmost", True)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)

        frame = ttk.Frame(self.window, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)

        for row, name in enumerate(("Title", "Score", "BREAK")):
            ttk.Label(frame, text=name).grid(row=row, column=0, sticky="e", padx=(0, 8), pady=4)
            entry = ttk.Entry(frame, width=36, justify=tk.RIGHT)
            entry.insert(0, self.initial_values[name])
            entry.grid(row=row, column=1, sticky="ew", pady=4)
            self.entries[name] = entry

        button_row = ttk.Frame(frame)
        button_row.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(button_row, text="취소", command=self.cancel).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(button_row, text="확인", command=self.submit).pack(side=tk.RIGHT)

        frame.columnconfigure(1, weight=1)
        self.window.bind("<Return>", lambda _event: self.submit())
        self.window.bind("<Escape>", lambda _event: self.cancel())

        self.window.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - self.window.winfo_reqwidth()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - self.window.winfo_reqheight()) // 2)
        self.window.geometry(f"+{x}+{y}")
        self.entries["Title"].focus_set()
        self.window.grab_set()
        self.root.wait_window(self.window)
        return self.result

    def submit(self) -> None:
        self.result = {
            name: entry.get().strip()
            for name, entry in self.entries.items()
        }
        if self.window is not None and self.window.winfo_exists():
            self.window.grab_release()
            self.window.destroy()

    def cancel(self) -> None:
        self.result = None
        if self.window is not None and self.window.winfo_exists():
            self.window.grab_release()
            self.window.destroy()
