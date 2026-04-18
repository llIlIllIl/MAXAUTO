from __future__ import annotations

from typing import Any

import tkinter as tk
from tkinter import ttk

from .system import monitor_frame_interval_ms


class RegistrationOverlay:
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
        self.window: tk.Toplevel | None = None
        self.progress_canvas: tk.Canvas | None = None
        self.finished = False
        self.cancelled = False
        self.elapsed_ms = 0
        self.timer_job: str | None = None
        self.animation_job: str | None = None

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

        screen_w = self.root.winfo_screenwidth()
        self.window.update_idletasks()
        self.width = min(max(self.width, self.window.winfo_reqwidth()), max(320, screen_w - (self.margin_right * 2)))
        self.height = max(self.height, self.window.winfo_reqheight())
        self.visible_x = screen_w - self.width - self.margin_right
        self.hidden_x = screen_w + 24
        self.y = self.margin_top
        self.window.geometry(f"{self.width}x{self.height}+{self.hidden_x}+{self.y}")
        self.window.deiconify()
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


class MessageOverlay:
    def __init__(
        self,
        root: tk.Tk,
        message: str,
        duration_seconds: int,
        on_close: Any,
    ) -> None:
        self.root = root
        self.message = message
        self.duration_seconds = max(1, int(duration_seconds))
        self.on_close = on_close
        self.window: tk.Toplevel | None = None
        self.progress_canvas: tk.Canvas | None = None
        self.timer_job: str | None = None
        self.animation_job: str | None = None
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

        screen_w = self.root.winfo_screenwidth()
        self.window.update_idletasks()
        self.width = min(max(self.width, self.window.winfo_reqwidth()), max(320, screen_w - (self.margin_right * 2)))
        self.height = max(self.height, self.window.winfo_reqheight())
        self.visible_x = screen_w - self.width - self.margin_right
        self.hidden_x = screen_w + 24
        self.y = self.margin_top
        self.window.geometry(f"{self.width}x{self.height}+{self.hidden_x}+{self.y}")
        self.window.deiconify()
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
