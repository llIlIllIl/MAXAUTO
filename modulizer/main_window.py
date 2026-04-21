from __future__ import annotations

import json
import os
import queue
import re
import threading
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from PIL import Image, ImageGrab, ImageTk

from .boxes import BoxRegion
from .config import (
    AppConfig,
    ConfigStore,
    MonitorSettings,
    OCRSettings,
    find_missing_required_boxes,
    parse_box_name_list,
)
from .constants import (
    APP_DIR,
    DEFAULT_CONFIG_PATH,
    DEFAULT_DEBUG_DIR,
    DEFAULT_MATCH_THRESHOLD,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_TEMPLATE_PATH,
    REQUIRED_BOX_NAMES,
    RESAMPLE_LANCZOS,
)
from .hotkeys import GlobalEnterListener
from .monitor_worker import MonitorWorker
from .ocr_service import OCRService
from .overlays import ManualOverlayInputDialog, MessageOverlay, RegistrationOverlay
from .record_store import ButtonRecordStore
from .v_archive_api import ScoreApiResult, VArchiveRecordClient, VArchiveScoreClient


STEAM_GAME_URL = "steam://rungameid/960170"


class MainApp:
    def __init__(self, root: tk.Tk, debug_mode: bool = False) -> None:
        self.root = root
        self.root.title("MAXOCR")
        self.root.geometry("1450x900")
        self.root.minsize(1100, 720)
        self.debug_mode = debug_mode

        self.config = AppConfig()
        self.record_store = ButtonRecordStore()
        self.score_client = VArchiveScoreClient()
        self.record_client = VArchiveRecordClient()
        self.image: Image.Image | None = None
        self.display_photo: ImageTk.PhotoImage | None = None
        self.scale_ratio = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.selected_box_index: int | None = None
        self.drag_start: tuple[int, int] | None = None
        self.drag_current: tuple[int, int] | None = None
        self.drag_mode: str | None = None
        self.drag_box_index: int | None = None
        self.drag_origin_image: tuple[int, int] | None = None
        self.drag_origin_box: BoxRegion | None = None
        self.reassign_box_index: int | None = None
        self.magnifier_photo: ImageTk.PhotoImage | None = None
        self.magnifier_radius = 12
        self.magnifier_zoom = 8
        self.coordinate_variables: dict[str, BoxRegion] = {}
        self.event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.worker: MonitorWorker | None = None
        self.global_enter_listener: GlobalEnterListener | None = None
        self.registration_overlay: RegistrationOverlay | None = None
        self.message_overlay: MessageOverlay | None = None
        self.message_overlay_close_log: str | None = None
        self.message_overlay_resume_on_close = True
        self.current_overlay_event: dict[str, Any] | None = None
        self.overlay_rerecognition_running = False
        self.manual_overlay_open = False
        self.ocr_model_thread: threading.Thread | None = None
        self.record_import_thread: threading.Thread | None = None
        self.record_import_button: ttk.Button | None = None

        self.vars = self._create_vars()
        self.box_edit_vars = self._create_box_edit_vars()
        self._build_ui()
        self._bind_events()
        self.clear_magnifier()
        self._load_default_config()
        self.start_ocr_model_preload()
        self.start_global_enter_listener()
        self._poll_worker_events()

    def _create_vars(self) -> dict[str, tk.Variable]:
        return {
            "min_confidence": tk.DoubleVar(value=0.0),
            "grayscale": tk.BooleanVar(value=False),
            "threshold": tk.BooleanVar(value=False),
            "threshold_value": tk.IntVar(value=140),
            "trigger_box_name": tk.StringVar(value="Button"),
            "template_path": tk.StringVar(value=str(DEFAULT_TEMPLATE_PATH) if DEFAULT_TEMPLATE_PATH.exists() else ""),
            "output_dir": tk.StringVar(value=str(DEFAULT_OUTPUT_DIR)),
            "interval_ms": tk.IntVar(value=500),
            "match_threshold": tk.DoubleVar(value=DEFAULT_MATCH_THRESHOLD),
            "numeric_box_names": tk.StringVar(value="Score, CLASS_NUM"),
            "overlay_timeout_seconds": tk.IntVar(value=10),
            "message_overlay_timeout_seconds": tk.IntVar(value=10),
            "compare_button_record": tk.BooleanVar(value=True),
            "save_screenshot": tk.BooleanVar(value=True),
            "pause_after_detection": tk.BooleanVar(value=True),
            "include_trigger_box_in_ocr": tk.BooleanVar(value=False),
            "score_outline_ocr": tk.BooleanVar(value=True),
            "record_import_nickname": tk.StringVar(value=""),
            "status": tk.StringVar(value="대기"),
            "score": tk.StringVar(value="-"),
        }

    def _create_box_edit_vars(self) -> dict[str, tk.Variable]:
        return {
            "name": tk.StringVar(value=""),
            "x1": tk.StringVar(value=""),
            "y1": tk.StringVar(value=""),
            "x2": tk.StringVar(value=""),
            "y2": tk.StringVar(value=""),
        }

    def _build_ui(self) -> None:
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        position_frame = ttk.LabelFrame(paned, text="1. 위치 설정", padding=8)
        right_frame = ttk.Frame(paned)
        paned.add(position_frame, weight=3)
        paned.add(right_frame, weight=1)

        self._build_position_section(position_frame)
        self._build_monitor_section(right_frame)
        self._build_settings_section(right_frame)

    def _build_position_section(self, parent: ttk.Frame) -> None:
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(toolbar, text="이미지 열기", command=self.open_image).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="설정 불러오기", command=self.load_config_dialog).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="설정 저장", command=self.save_config_dialog).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="선택 삭제", command=self.delete_selected_box).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="전체 삭제", command=self.clear_boxes).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="트리거 템플릿 추출", command=self.extract_trigger_template).pack(side=tk.LEFT)

        body = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True)

        canvas_frame = ttk.Frame(body)
        list_frame = ttk.Frame(body)
        body.add(canvas_frame, weight=3)
        body.add(list_frame, weight=1)

        self.canvas = tk.Canvas(canvas_frame, bg="#20242a", cursor="crosshair", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.box_list = tk.Listbox(list_frame, width=40, height=18, exportselection=False)
        self.box_list.pack(fill=tk.BOTH, expand=True)
        self.box_list.bind("<<ListboxSelect>>", self.on_box_selected)

        edit_frame = ttk.LabelFrame(list_frame, text="좌표", padding=6)
        edit_frame.pack(fill=tk.X, pady=(8, 0))
        edit_grid = ttk.Frame(edit_frame)
        edit_grid.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(edit_grid, text="name").grid(row=0, column=0, sticky="w", padx=(0, 4), pady=2)
        ttk.Entry(edit_grid, textvariable=self.box_edit_vars["name"], width=18, state="readonly").grid(row=0, column=1, columnspan=3, sticky="ew", pady=2)
        for column, name in enumerate(("x1", "y1", "x2", "y2")):
            ttk.Label(edit_grid, text=name).grid(row=1, column=column, sticky="w", padx=(0, 4), pady=2)
            ttk.Entry(edit_grid, textvariable=self.box_edit_vars[name], width=7, state="readonly").grid(row=2, column=column, sticky="ew", padx=(0, 4), pady=2)
        ttk.Button(edit_grid, text="박스 재지정", command=self.start_box_reassign).grid(row=3, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        for column in range(4):
            edit_grid.columnconfigure(column, weight=1)

        self.coord_text = tk.Text(edit_frame, height=7, width=35, state=tk.DISABLED)
        self.coord_text.pack(fill=tk.X)

        magnifier_frame = ttk.LabelFrame(list_frame, text="확대", padding=6)
        magnifier_frame.pack(fill=tk.X, pady=(8, 0))
        magnifier_size = (self.magnifier_radius * 2 + 1) * self.magnifier_zoom
        self.magnifier_canvas = tk.Canvas(
            magnifier_frame,
            width=magnifier_size,
            height=magnifier_size,
            bg="#111820",
            highlightthickness=0,
        )
        self.magnifier_canvas.pack()
        self.magnifier_label = ttk.Label(magnifier_frame, text="x=-, y=-")
        self.magnifier_label.pack(anchor="w", pady=(6, 0))

    def _build_monitor_section(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="2. 실시간 이미지 인식 및 다운로드", padding=8)
        frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        controls = ttk.Frame(frame)
        controls.pack(fill=tk.X)
        ttk.Button(controls, text="시작", command=self.start_monitor).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(controls, text="게임과 함께 시작", command=self.start_monitor_with_game).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(controls, text="중지", command=self.stop_monitor).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(controls, text="Enter 재개", command=self.resume_monitor).pack(side=tk.LEFT)

        status_grid = ttk.Frame(frame)
        status_grid.pack(fill=tk.X, pady=8)
        ttk.Label(status_grid, text="상태").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Label(status_grid, textvariable=self.vars["status"]).grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(status_grid, text="점수").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Label(status_grid, textvariable=self.vars["score"]).grid(row=1, column=1, sticky="w", pady=2)

        self.log_text = ScrolledText(frame, height=14, wrap=tk.WORD, font=("Consolas", 10))
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _build_settings_section(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="3. 설정", padding=8)
        frame.pack(fill=tk.BOTH, expand=True)

        row = 0
        ttk.Label(frame, text="트리거 박스").grid(row=row, column=0, sticky="w", pady=3)
        self.trigger_combo = ttk.Combobox(
            frame,
            textvariable=self.vars["trigger_box_name"],
            values=[],
            state="readonly",
            width=22,
        )
        self.trigger_combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        self.trigger_combo.bind("<<ComboboxSelected>>", lambda _event: self.redraw_canvas())

        row += 1
        ttk.Label(frame, text="템플릿 이미지").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(frame, textvariable=self.vars["template_path"]).grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(frame, text="찾기", command=self.pick_template_path).grid(row=row, column=2, padx=(6, 0), pady=3)

        row += 1
        ttk.Label(frame, text="저장 폴더").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(frame, textvariable=self.vars["output_dir"]).grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(frame, text="찾기", command=self.pick_output_dir).grid(row=row, column=2, padx=(6, 0), pady=3)

        row += 1
        ttk.Label(frame, text="감시 간격(ms)").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Spinbox(frame, from_=100, to=10000, increment=100, textvariable=self.vars["interval_ms"], width=8).grid(
            row=row, column=1, sticky="w", pady=3
        )

        row += 1
        ttk.Label(frame, text="매칭 기준").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Spinbox(frame, from_=0.1, to=1.0, increment=0.01, textvariable=self.vars["match_threshold"], width=8).grid(
            row=row, column=1, sticky="w", pady=3
        )

        row += 1
        ttk.Label(frame, text="숫자 박스").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(frame, textvariable=self.vars["numeric_box_names"]).grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)

        row += 1
        ttk.Label(frame, text="유저 닉네임").grid(row=row, column=0, sticky="w", pady=3)
        import_frame = ttk.Frame(frame)
        import_frame.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
        ttk.Entry(import_frame, textvariable=self.vars["record_import_nickname"]).pack(
            side=tk.LEFT,
            fill=tk.X,
            expand=True,
        )
        self.record_import_button = ttk.Button(
            import_frame,
            text="기록 가져오기",
            command=self.start_record_import,
        )
        self.record_import_button.pack(side=tk.LEFT, padx=(6, 0))
        import_frame.columnconfigure(0, weight=1)

        row += 1
        ttk.Label(frame, text="점수반영 오버레이 시간(초)").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Spinbox(frame, from_=1, to=60, increment=1, textvariable=self.vars["overlay_timeout_seconds"], width=8).grid(
            row=row, column=1, sticky="w", pady=3
        )

        row += 1
        ttk.Label(frame, text="메시지 오버레이 시간(초)").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Spinbox(
            frame,
            from_=1,
            to=60,
            increment=1,
            textvariable=self.vars["message_overlay_timeout_seconds"],
            width=8,
        ).grid(row=row, column=1, sticky="w", pady=3)

        if self.debug_mode:
            row += 1
            ttk.Label(frame, text="Paddle min confidence").grid(row=row, column=0, sticky="w", pady=3)
            ttk.Spinbox(
                frame,
                from_=0.0,
                to=1.0,
                increment=0.05,
                textvariable=self.vars["min_confidence"],
                width=8,
            ).grid(row=row, column=1, sticky="w", pady=3)

        row += 1
        checks = ttk.Frame(frame)
        checks.grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Checkbutton(checks, text="스크린샷 저장", variable=self.vars["save_screenshot"]).pack(anchor="w")
        ttk.Checkbutton(checks, text="감지 후 Enter까지 정지", variable=self.vars["pause_after_detection"]).pack(anchor="w")
        ttk.Checkbutton(checks, text="기록 갱신 비교", variable=self.vars["compare_button_record"]).pack(anchor="w")
        ttk.Checkbutton(checks, text="트리거 박스 OCR 포함", variable=self.vars["include_trigger_box_in_ocr"]).pack(anchor="w")
        ttk.Checkbutton(checks, text="Score 윤곽선 OCR", variable=self.vars["score_outline_ocr"]).pack(anchor="w")
        ttk.Checkbutton(checks, text="흑백 전처리", variable=self.vars["grayscale"]).pack(anchor="w")
        ttk.Checkbutton(checks, text="임계값 전처리", variable=self.vars["threshold"]).pack(anchor="w")

        row += 1
        ttk.Label(frame, text="임계값").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Spinbox(frame, from_=0, to=255, increment=1, textvariable=self.vars["threshold_value"], width=8).grid(
            row=row, column=1, sticky="w", pady=3
        )
        if not self.debug_mode:
            for child in checks.winfo_children()[3:]:
                child.destroy()
            for child in frame.grid_slaves(row=row):
                child.destroy()
        frame.columnconfigure(1, weight=1)

    def _bind_events(self) -> None:
        self.canvas.bind("<Button-1>", self.on_canvas_down)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_up)
        self.canvas.bind("<Motion>", self.on_canvas_motion)
        self.canvas.bind("<Leave>", self.on_canvas_leave)
        self.canvas.bind("<Configure>", lambda _event: self.redraw_canvas())
        self.root.bind_all("<Return>", lambda _event: self.handle_enter_key())
        self.root.bind_all("<Delete>", lambda _event: self.handle_delete_key())
        self.root.bind_all("<Insert>", lambda _event: self.handle_insert_key())
        self.root.bind_all("<KeyPress-equal>", lambda _event: self.handle_manual_overlay_key())
        self.vars["numeric_box_names"].trace_add("write", lambda *_args: self.refresh_box_list())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def start_global_enter_listener(self) -> None:
        if self.global_enter_listener is not None and self.global_enter_listener.is_alive():
            return
        self.global_enter_listener = GlobalEnterListener(self.event_queue)
        self.global_enter_listener.start()

    def start_ocr_model_preload(self) -> None:
        if self.ocr_model_thread is not None and self.ocr_model_thread.is_alive():
            return

        settings = self.config.ocr_settings

        def worker() -> None:
            missing_models = OCRService.missing_required_model_names()
            if missing_models:
                self.event_queue.put(
                    {
                        "type": "status",
                        "message": f"PaddleOCR 한국어 모델 다운로드 중: {', '.join(missing_models)}",
                    }
                )
            else:
                self.event_queue.put({"type": "status", "message": "PaddleOCR 한국어 모델 준비 중"})
            try:
                downloaded = OCRService(settings).prepare_model()
            except Exception as exc:
                self.event_queue.put({"type": "error", "message": f"PaddleOCR 한국어 모델 준비 실패: {exc}"})
                return
            if downloaded:
                message = "PaddleOCR 한국어 모델 다운로드 및 준비 완료"
            else:
                message = "PaddleOCR 한국어 모델 준비 완료"
            self.event_queue.put({"type": "status", "message": message})

        self.ocr_model_thread = threading.Thread(target=worker, daemon=True)
        self.ocr_model_thread.start()

    def _load_default_config(self) -> None:
        if DEFAULT_CONFIG_PATH.exists():
            try:
                self.apply_config(ConfigStore.load(DEFAULT_CONFIG_PATH))
                self.append_log(f"기본 설정 불러옴: {DEFAULT_CONFIG_PATH.name}")
                return
            except Exception as exc:
                self.append_log(f"기본 설정 불러오기 실패: {exc}")
        self.sync_config_to_vars()
        self.refresh_box_list()

    def make_config_from_vars(self) -> AppConfig:
        return AppConfig(
            image_path=self.config.image_path,
            ocr_settings=OCRSettings(
                min_confidence=float(self.vars["min_confidence"].get()),
                grayscale=bool(self.vars["grayscale"].get()),
                threshold=bool(self.vars["threshold"].get()),
                threshold_value=int(self.vars["threshold_value"].get()),
            ),
            monitor_settings=MonitorSettings(
                trigger_box_name=str(self.vars["trigger_box_name"].get()),
                template_path=str(self.vars["template_path"].get()),
                output_dir=str(self.vars["output_dir"].get()),
                interval_ms=int(self.vars["interval_ms"].get()),
                match_threshold=float(self.vars["match_threshold"].get()),
                numeric_box_names=parse_box_name_list(str(self.vars["numeric_box_names"].get())),
                overlay_timeout_seconds=int(self.vars["overlay_timeout_seconds"].get()),
                message_overlay_timeout_seconds=int(self.vars["message_overlay_timeout_seconds"].get()),
                compare_button_record=bool(self.vars["compare_button_record"].get()),
                save_screenshot=bool(self.vars["save_screenshot"].get()),
                pause_after_detection=bool(self.vars["pause_after_detection"].get()),
                include_trigger_box_in_ocr=bool(self.vars["include_trigger_box_in_ocr"].get()),
                score_outline_ocr=bool(self.vars["score_outline_ocr"].get()),
                record_import_nickname=str(self.vars["record_import_nickname"].get()).strip(),
            ),
            manual_boxes=[box.normalized() for box in self.config.manual_boxes],
        )

    def sync_config_to_vars(self) -> None:
        ocr = self.config.ocr_settings
        monitor = self.config.monitor_settings
        self.vars["min_confidence"].set(ocr.min_confidence)
        self.vars["grayscale"].set(ocr.grayscale)
        self.vars["threshold"].set(ocr.threshold)
        self.vars["threshold_value"].set(ocr.threshold_value)
        self.vars["trigger_box_name"].set(monitor.trigger_box_name)
        self.vars["template_path"].set(monitor.template_path)
        self.vars["output_dir"].set(monitor.output_dir)
        self.vars["interval_ms"].set(monitor.interval_ms)
        self.vars["match_threshold"].set(monitor.match_threshold)
        self.vars["numeric_box_names"].set(", ".join(monitor.numeric_box_names))
        self.vars["overlay_timeout_seconds"].set(monitor.overlay_timeout_seconds)
        self.vars["message_overlay_timeout_seconds"].set(monitor.message_overlay_timeout_seconds)
        self.vars["compare_button_record"].set(monitor.compare_button_record)
        self.vars["save_screenshot"].set(monitor.save_screenshot)
        self.vars["pause_after_detection"].set(monitor.pause_after_detection)
        self.vars["include_trigger_box_in_ocr"].set(monitor.include_trigger_box_in_ocr)
        self.vars["score_outline_ocr"].set(monitor.score_outline_ocr)
        self.vars["record_import_nickname"].set(monitor.record_import_nickname)

    def apply_config(self, config: AppConfig) -> None:
        self.config = config
        self.sync_config_to_vars()
        self.load_image_from_path(config.image_path, silent=True)
        self.refresh_box_list()
        self.redraw_canvas()

    def open_image(self) -> None:
        path = filedialog.askopenfilename(
            title="이미지 열기",
            filetypes=[("Image Files", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"), ("All Files", "*.*")],
        )
        if path:
            self.load_image_from_path(path, silent=False)

    def load_image_from_path(self, path: str, silent: bool) -> None:
        if not path:
            self.image = None
            self.config.image_path = ""
            self.redraw_canvas()
            return
        image_path = Path(path)
        if not image_path.exists():
            self.image = None
            self.config.image_path = path
            if not silent:
                messagebox.showwarning("이미지 없음", f"이미지를 찾을 수 없습니다.\n{image_path.name or path}")
            self.redraw_canvas()
            return
        try:
            self.image = Image.open(image_path).convert("RGB")
            self.config.image_path = str(image_path)
            self.append_log(f"이미지 열기: {image_path.name}")
            self.redraw_canvas()
        except Exception as exc:
            if not silent:
                messagebox.showerror("이미지 오류", str(exc))

    def load_config_dialog(self) -> None:
        path = filedialog.askopenfilename(
            title="설정 불러오기",
            initialdir=str(APP_DIR),
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            self.apply_config(ConfigStore.load(Path(path)))
            self.append_log(f"설정 불러옴: {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("설정 오류", str(exc))

    def save_config_dialog(self) -> None:
        path = filedialog.asksaveasfilename(
            title="설정 저장",
            initialdir=str(APP_DIR),
            initialfile="OCR.json",
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            self.config = self.make_config_from_vars()
            ConfigStore.save(Path(path), self.config)
            self.append_log(f"설정 저장됨: {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("저장 오류", str(exc))

    def pick_template_path(self) -> None:
        path = filedialog.askopenfilename(
            title="템플릿 이미지",
            initialdir=str(APP_DIR),
            filetypes=[("Image Files", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"), ("All Files", "*.*")],
        )
        if path:
            self.vars["template_path"].set(path)

    def pick_output_dir(self) -> None:
        path = filedialog.askdirectory(title="저장 폴더", initialdir=str(APP_DIR))
        if path:
            self.vars["output_dir"].set(path)

    def start_record_import(self) -> None:
        if self.record_import_thread is not None and self.record_import_thread.is_alive():
            return
        nickname = str(self.vars["record_import_nickname"].get()).strip()
        if not nickname:
            messagebox.showwarning("닉네임 필요", "기록을 가져올 유저 닉네임을 입력하세요.")
            return
        if not messagebox.askyesno(
            "기록 가져오기 확인",
            "기존에 존재하는 내역이 전부 삭제됩니다. 진행하시겠습니까?",
        ):
            self.append_log("기록 가져오기 취소")
            return

        self.config = self.make_config_from_vars()
        self.set_record_import_busy(True)
        self.vars["status"].set("기록 가져오는 중")
        self.append_log(f"기록 가져오기 시작: {nickname}")
        self.record_import_thread = threading.Thread(
            target=self._record_import_worker,
            args=(nickname,),
            daemon=True,
        )
        self.record_import_thread.start()

    def set_record_import_busy(self, busy: bool) -> None:
        if self.record_import_button is not None:
            self.record_import_button.configure(state=tk.DISABLED if busy else tk.NORMAL)

    def _record_import_worker(self, nickname: str) -> None:
        try:
            button_results = self.record_client.fetch_all(nickname)
            saved_results: list[dict[str, Any]] = []
            for result in button_results:
                path = self.record_store.replace_button_records(result.button, result.records)
                saved_count = sum(len(title_records) for title_records in result.records.values())
                saved_results.append(
                    {
                        "button": result.button,
                        "api_count": result.count,
                        "saved_count": saved_count,
                        "path": str(path),
                    }
                )
            self.event_queue.put(
                {
                    "type": "record_import_result",
                    "nickname": nickname,
                    "results": saved_results,
                }
            )
        except Exception as exc:
            self.event_queue.put({"type": "record_import_error", "message": str(exc)})

    def extract_trigger_template(self) -> None:
        if self.image is None:
            messagebox.showwarning("이미지 필요", "템플릿을 추출할 기준 이미지를 먼저 여세요.")
            return
        trigger = self.find_box(str(self.vars["trigger_box_name"].get()))
        if trigger is None:
            messagebox.showwarning("박스 없음", "트리거 박스를 선택하세요.")
            return
        path = filedialog.asksaveasfilename(
            title="트리거 템플릿 저장",
            initialdir=str(APP_DIR),
            initialfile=f"{trigger.name}.png",
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            trigger.crop(self.image).save(path)
            self.vars["template_path"].set(path)
            self.append_log(f"템플릿 저장됨: {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("템플릿 오류", str(exc))

    def save_trigger_debug_capture(self) -> None:
        config = self.make_config_from_vars()
        trigger = None
        for box in config.manual_boxes:
            if box.name == config.monitor_settings.trigger_box_name:
                trigger = box.normalized()
                break
        if trigger is None:
            messagebox.showwarning("박스 없음", "트리거 박스를 찾을 수 없습니다.")
            return

        try:
            screenshot = ImageGrab.grab().convert("RGB")
            roi = trigger.crop(screenshot)
            matcher = TemplateMatcher(config.monitor_settings.template_path)
            score = matcher.compare(roi)

            output_dir = Path(config.monitor_settings.output_dir).expanduser()
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            roi_path = output_dir / f"trigger_roi_{timestamp}.png"
            roi.save(roi_path)

            template_size = matcher.template.size if matcher.template is not None else None
            self.vars["score"].set(f"{score:.4f}")
            self.append_log(
                f"트리거 캡처: {roi_path.name} / roi={roi.size} / template={template_size} / score={score:.4f}"
            )
        except Exception as exc:
            messagebox.showerror("트리거 캡처 오류", str(exc))

    def start_monitor(self) -> bool:
        if self.worker is not None and self.worker.is_alive():
            return True
        config = self.make_config_from_vars()
        if not config.manual_boxes:
            messagebox.showwarning("좌표 없음", "먼저 OCR 박스를 하나 이상 지정하세요.")
            return False
        missing_required = find_missing_required_boxes(config.manual_boxes)
        if missing_required:
            missing_text = ", ".join(missing_required)
            message = f"필수 박스 좌표가 지정되지 않았습니다: {missing_text}"
            messagebox.showwarning("필수 박스 없음", message)
            self.vars["status"].set("필수 박스 누락")
            self.append_log(message)
            return False
        if not config.monitor_settings.template_path:
            messagebox.showwarning("템플릿 없음", "트리거 템플릿 이미지를 지정하세요.")
            return False
        self.config = config
        self.worker = MonitorWorker(config, config.manual_boxes, self.event_queue)
        self.worker.start()
        self.vars["status"].set("감시 중")
        self.append_log("감시 스레드 시작")
        return True

    def start_monitor_with_game(self) -> None:
        was_running = self.worker is not None and self.worker.is_alive()
        if not self.start_monitor():
            return
        if not self.launch_steam_game() and not was_running:
            self.stop_monitor()

    def launch_steam_game(self) -> bool:
        try:
            os.startfile(STEAM_GAME_URL)  # type: ignore[attr-defined]
        except OSError as exc:
            message = f"Steam 게임 실행 실패: {exc}"
            self.vars["status"].set("게임 실행 실패")
            self.append_log(message)
            messagebox.showerror("게임 실행 오류", message)
            return False
        self.append_log(f"Steam 게임 실행 요청: {STEAM_GAME_URL}")
        return True

    def stop_monitor(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.worker = None
        self.vars["status"].set("중지")
        self.append_log("감시 중지 요청")

    def resume_monitor(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            was_paused = not self.worker.resume_event.is_set()
            self.worker.resume()
            if was_paused:
                self.vars["status"].set("감시 중")
                self.append_log("Enter 재개")

    def handle_enter_key(self) -> None:
        if self.registration_overlay is not None:
            self.accept_registration_overlay(source="enter")
            return
        if self.message_overlay is not None:
            overlay = self.message_overlay
            self.message_overlay_resume_on_close = True
            overlay.close()
            return
        self.resume_monitor()

    def handle_delete_key(self) -> None:
        if self.registration_overlay is not None:
            self.cancel_registration_overlay()

    def handle_insert_key(self) -> None:
        if self.registration_overlay is not None:
            self.retry_registration_overlay()

    def handle_manual_overlay_key(self) -> None:
        self.request_manual_overlay_input()

    def accept_registration_overlay(self, source: str = "manual") -> None:
        if self.registration_overlay is not None:
            overlay = self.registration_overlay
            self.registration_overlay = None
            overlay.accept()
            return
        self.resume_monitor()

    def cancel_registration_overlay(self) -> None:
        if self.registration_overlay is not None:
            overlay = self.registration_overlay
            self.registration_overlay = None
            overlay.cancel()

    def retry_registration_overlay(self) -> None:
        if self.registration_overlay is not None:
            overlay = self.registration_overlay
            self.registration_overlay = None
            overlay.retry()

    def on_overlay_accepted(self) -> None:
        event = self.current_overlay_event
        self.registration_overlay = None
        self.current_overlay_event = None
        if event is None:
            self.resume_monitor()
            return

        values = self._overlay_values_from_event(event)
        self.vars["status"].set("API 등록 중")
        self.append_log("API 등록 요청")
        threading.Thread(target=self._submit_score_api_worker, args=(values,), daemon=True).start()

    def _submit_score_api_worker(self, values: dict[str, str]) -> None:
        try:
            result = self.score_client.submit(values)
            self.event_queue.put({"type": "score_api_result", "result": result, "values": values})
        except Exception as exc:
            self.event_queue.put({"type": "score_api_error", "message": str(exc), "values": values})

    def on_overlay_cancelled(self) -> None:
        self.registration_overlay = None
        self.current_overlay_event = None
        self.append_log("취소됨")

    def on_overlay_retry(self) -> None:
        self.registration_overlay = None
        self.current_overlay_event = None
        self.append_log("재인식")
        self.resume_monitor()

    def on_overlay_manual(self) -> None:
        self.registration_overlay = None
        self.request_manual_overlay_input()

    def request_manual_overlay_input(self) -> None:
        if self.manual_overlay_open:
            return
        source_event = self.current_overlay_event
        if source_event is None:
            return
        if self.message_overlay is not None:
            overlay = self.message_overlay
            self.message_overlay = None
            overlay.close_now()
        if self.registration_overlay is not None:
            overlay = self.registration_overlay
            self.registration_overlay = None
            overlay.close_now()
        self.root.after(0, lambda event=source_event: self.open_manual_overlay_input(event))

    def open_manual_overlay_input(self, source_event: dict[str, Any] | None = None) -> None:
        source_event = source_event or self.current_overlay_event
        if source_event is None or self.manual_overlay_open:
            return
        self.manual_overlay_open = True

        defaults = self._overlay_values_from_event(source_event)
        try:
            dialog = ManualOverlayInputDialog(
                self.root,
                title=defaults.get("Title", ""),
                score=defaults.get("Score", ""),
                break_value=defaults.get("BREAK", ""),
            )
            manual_values = dialog.show()
        finally:
            self.manual_overlay_open = False
        if manual_values is None:
            self.show_registration_overlay(source_event)
            return

        manual_event = self._manual_overlay_event(source_event, manual_values)
        try:
            debug_dir = self.save_manual_debug_data(source_event, manual_values)
            manual_event["manual_debug_dir"] = str(debug_dir)
            self.append_log(f"수동 입력 저장: {debug_dir.name}")
        except Exception as exc:
            self.append_log(f"수동 입력 저장 오류: {exc}")
        self.show_registration_overlay(manual_event)

    def _manual_overlay_event(self, source_event: dict[str, Any], manual_values: dict[str, str]) -> dict[str, Any]:
        manual_event = dict(source_event)
        target_names = ("Title", "Score", "BREAK")
        remaining = set(target_names)
        results: list[dict[str, str]] = []

        for item in source_event.get("results", []):
            if not isinstance(item, dict):
                continue
            copied = dict(item)
            name = str(copied.get("name", ""))
            if name in remaining:
                copied["manual_original_text"] = str(copied.get("text", ""))
                copied["text"] = str(manual_values.get(name, "")).strip()
                copied["manual_override"] = "true"
                remaining.remove(name)
            results.append(copied)

        for name in target_names:
            if name not in remaining:
                continue
            box = self.find_box(name)
            normalized = box.normalized() if box is not None else None
            coords = (
                f"{normalized.x1},{normalized.y1},{normalized.x2},{normalized.y2}"
                if normalized is not None
                else ""
            )
            results.append(
                {
                    "name": name,
                    "coords": coords,
                    "ocr_lang": "manual",
                    "ocr_preprocess": "manual",
                    "text": str(manual_values.get(name, "")).strip(),
                    "error": "",
                    "manual_override": "true",
                }
            )

        manual_event["results"] = results
        manual_event["manual_overlay"] = True
        manual_event["manual_values"] = {
            name: str(manual_values.get(name, "")).strip()
            for name in target_names
        }
        return manual_event

    def save_manual_debug_data(self, source_event: dict[str, Any], manual_values: dict[str, str]) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        debug_dir = DEFAULT_DEBUG_DIR / timestamp
        suffix = 1
        while debug_dir.exists():
            debug_dir = DEFAULT_DEBUG_DIR / f"{timestamp}_{suffix}"
            suffix += 1
        debug_dir.mkdir(parents=True, exist_ok=False)

        debug_crops = source_event.get("debug_crops", {})
        if isinstance(debug_crops, dict):
            for name in ("Title", "BREAK", "Score"):
                crop = debug_crops.get(name)
                if isinstance(crop, Image.Image):
                    crop_path = debug_dir / f"{name}.png"
                    crop.save(crop_path)

        original_values = self._overlay_values_from_event(source_event)
        coords = self._overlay_coords_from_event(source_event)
        manual_clean = {
            name: str(manual_values.get(name, "")).strip()
            for name in ("Title", "Score", "BREAK")
        }
        info = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_timestamp": source_event.get("timestamp", ""),
            "original": original_values,
            "manual": manual_clean,
            "coords": coords,
        }
        (debug_dir / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        info_lines = [
            f"created_at: {info['created_at']}",
            f"source_timestamp: {info['source_timestamp']}",
            "",
            "[original]",
            f"Title: {original_values.get('Title', '')}",
            f"Score: {original_values.get('Score', '')}",
            f"BREAK: {original_values.get('BREAK', '')}",
            "",
            "[manual]",
            f"Title: {manual_clean.get('Title', '')}",
            f"Score: {manual_clean.get('Score', '')}",
            f"BREAK: {manual_clean.get('BREAK', '')}",
        ]
        (debug_dir / "info.txt").write_text("\n".join(info_lines), encoding="utf-8")
        return debug_dir

    def _overlay_values_from_event(self, event: dict[str, Any]) -> dict[str, str]:
        values = {
            "Title": "",
            "Score": "",
            "BREAK": "",
            "Button": str(event.get("trigger_box_name", "")),
            "difficult": "",
            "ARTIST": "",
        }
        for item in event.get("results", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            if name in values:
                values[name] = str(item.get("text", "")).strip()
        return values

    def _overlay_coords_from_event(self, event: dict[str, Any]) -> dict[str, str]:
        coords = {"Title": "", "Score": "", "BREAK": "", "Button": "", "difficult": "", "ARTIST": ""}
        for item in event.get("results", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            if name in coords:
                coords[name] = str(item.get("coords", "")).strip()
        return coords

    def show_registration_overlay(self, event: dict[str, Any]) -> None:
        if self.message_overlay is not None:
            overlay = self.message_overlay
            self.message_overlay = None
            overlay.close_now()
        if self.registration_overlay is not None:
            self.registration_overlay.close_now()
            self.registration_overlay = None
        self.current_overlay_event = event

        results = event.get("results", [])
        result_map = {
            str(item.get("name", "")): str(item.get("text", "")).strip()
            for item in results
            if isinstance(item, dict)
        }
        button = self._compact_overlay_value(
            result_map.get("Button", str(event.get("trigger_box_name", "Button")))
        )
        difficult = self._compact_overlay_value(result_map.get("difficult", ""))
        title = self._compact_overlay_value(result_map.get("Title", ""))
        score = self._compact_overlay_value(result_map.get("Score", ""))
        break_value = self._compact_overlay_value(result_map.get("BREAK", ""))
        score_color, score_suffix = self._overlay_score_style(score, break_value)
        heading = "아래 결과를 등록합니다."
        footer = (
            "등록을 원치 않으면 \"Delete\" 버튼을 눌러주세요.\n"
            "재인식을 원하시면 \"Insert\" 버튼을 눌러주세요.\n"
            "직접 입력하려면 \"=\" 키를 눌러주세요."
        )
        timeout_seconds = int(self.vars["overlay_timeout_seconds"].get())
        self.registration_overlay = RegistrationOverlay(
            self.root,
            heading=heading,
            result_difficult=difficult,
            result_button=button,
            result_title=title,
            result_score=score,
            result_score_color=score_color,
            result_suffix=score_suffix,
            footer=footer,
            duration_seconds=timeout_seconds,
            on_accept=self.on_overlay_accepted,
            on_cancel=self.on_overlay_cancelled,
            on_retry=self.on_overlay_retry,
            on_manual=self.on_overlay_manual,
        )
        self.registration_overlay.show()

    def should_show_registration_overlay(self, event: dict[str, Any]) -> bool:
        if not bool(self.vars["compare_button_record"].get()):
            return True
        values = self._overlay_values_from_event(event)
        decision = self.record_store.compare(values)
        event["record_decision"] = {
            "should_register": decision.should_register,
            "reason": decision.reason,
            "path": str(decision.path),
            "difficult": decision.difficult,
            "title": decision.title,
            "button": decision.button,
            "current_score": decision.current_score,
            "current_fc": decision.current_fc,
            "stored_score": decision.stored_score,
            "stored_fc": decision.stored_fc,
        }
        self.append_log(f"기록 비교: {decision.reason} ({decision.path.name})")
        return decision.should_register

    def show_record_failure_overlay(self, event: dict[str, Any]) -> None:
        resume_on_close = not bool(
            event.get("pause_after_detection", self.vars["pause_after_detection"].get())
        )
        self.show_message_overlay(
            event,
            message="현재 플레이한 곡의 기록 갱신에 실패하였습니다.",
            log_message="기록 갱신 실패",
            resume_on_close=resume_on_close,
        )

    def show_message_overlay(
        self,
        event: dict[str, Any] | None,
        message: str,
        log_message: str | None = None,
        resume_on_close: bool = True,
    ) -> None:
        message = self._shorten_paths_in_message(message)
        if log_message is not None:
            log_message = self._shorten_paths_in_message(log_message)
        if self.registration_overlay is not None:
            overlay = self.registration_overlay
            self.registration_overlay = None
            overlay.close_now()
        if self.message_overlay is not None:
            overlay = self.message_overlay
            self.message_overlay = None
            overlay.close_now()
        self.current_overlay_event = event
        self.message_overlay_close_log = log_message or message
        self.message_overlay_resume_on_close = resume_on_close
        timeout_seconds = int(self.vars["message_overlay_timeout_seconds"].get())
        self.message_overlay = MessageOverlay(
            self.root,
            message=message,
            duration_seconds=timeout_seconds,
            on_close=self.on_message_overlay_closed,
        )
        self.message_overlay.show()

    def on_message_overlay_closed(self) -> None:
        resume_on_close = self.message_overlay_resume_on_close
        self.message_overlay = None
        self.current_overlay_event = None
        if self.message_overlay_close_log:
            self.append_log(self.message_overlay_close_log)
        self.message_overlay_close_log = None
        self.message_overlay_resume_on_close = True
        if resume_on_close:
            self.resume_monitor()

    def handle_score_api_result(self, result: ScoreApiResult, values: dict[str, str]) -> None:
        if result.success:
            try:
                record_path = self.record_store.update(values)
                self.append_log(f"기록 저장: {record_path.name}")
            except Exception as exc:
                self.append_log(f"기록 저장 오류: {exc}")
                self.show_message_overlay(None, message=f"기록 저장 오류: {exc}", log_message=f"기록 저장 오류: {exc}")
                return
            if result.message:
                self.show_message_overlay(None, message=result.message, log_message=result.message)
                return
            self.vars["status"].set("등록 완료")
            self.show_message_overlay(
                None,
                message="스코어가 정상적으로 등록되었습니다.",
                log_message="등록됨",
            )
            return

        message = result.message or "API 요청 실패"
        self.show_message_overlay(None, message=message, log_message=message)

    def handle_score_api_error(self, message: str) -> None:
        clean_message = str(message).strip() or "API 요청 실패"
        self.show_message_overlay(None, message=clean_message, log_message=clean_message)

    def handle_record_import_result(self, nickname: str, results: list[dict[str, Any]]) -> None:
        self.set_record_import_busy(False)
        summary_parts = []
        total_saved = 0
        for result in results:
            button = result.get("button")
            saved_count = int(result.get("saved_count", 0))
            total_saved += saved_count
            path_name = Path(str(result.get("path", ""))).name
            summary_parts.append(f"{button}B {saved_count}건({path_name})")
        summary = ", ".join(summary_parts)
        message = f"{nickname} 기록 가져오기 완료: {summary}"
        self.vars["status"].set("기록 가져오기 완료")
        self.append_log(message)
        messagebox.showinfo(
            "기록 가져오기",
            f"{nickname} 기록을 가져왔습니다.\n총 {total_saved}건\n{summary}",
        )

    def handle_record_import_error(self, message: str) -> None:
        self.set_record_import_busy(False)
        clean_message = str(message).strip() or "기록 가져오기 실패"
        self.vars["status"].set("기록 가져오기 실패")
        self.append_log(f"기록 가져오기 실패: {clean_message}")
        messagebox.showerror("기록 가져오기 오류", clean_message)

    @staticmethod
    def _compact_overlay_value(value: str) -> str:
        compacted = " ".join(str(value).split())
        return compacted if compacted else "-"

    @staticmethod
    def _overlay_score_style(score: str, break_value: str) -> tuple[str, str]:
        score_color = "white"
        score_suffix = ""
        score_digits = "".join(char for char in score if char.isdigit())
        if MainApp._is_zero_break_value(break_value):
            score_color = "#48eeaa"
        if score_digits == "1000000":
            score_color = "#f2ff1a"
            score_suffix = "[MAXIMUM]"
        return score_color, score_suffix

    @staticmethod
    def _is_zero_break_value(value: str) -> bool:
        normalized = unicodedata.normalize("NFKC", str(value)).strip()
        if not normalized or normalized == "-":
            return True
        normalized = normalized.translate(str.maketrans({"O": "0", "o": "0"}))
        digits = "".join(char for char in normalized if char.isdigit())
        return bool(digits) and int(digits) == 0

    def _poll_worker_events(self) -> None:
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            self.handle_worker_event(event)
        self.root.after(100, self._poll_worker_events)

    def handle_worker_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "score":
            self.vars["score"].set(f"{float(event.get('score', 0.0)):.4f}")
        elif event_type == "status":
            self.vars["status"].set(str(event.get("message", "")))
            self.append_log(str(event.get("message", "")))
        elif event_type == "paused":
            self.vars["status"].set("Enter 대기")
            self.append_log(str(event.get("message", "")))
        elif event_type == "detected":
            self.vars["status"].set("감지 완료")
            self.vars["score"].set(f"{float(event.get('score', 0.0)):.4f}")
            if event.get("text_path"):
                self.append_log(f"감지됨: {Path(str(event.get('text_path'))).name}")
            else:
                self.append_log("감지됨")
            if event.get("screenshot_path"):
                self.append_log(f"스크린샷: {Path(str(event.get('screenshot_path'))).name}")
            if self.should_show_registration_overlay(event):
                self.show_registration_overlay(event)
            else:
                self.show_record_failure_overlay(event)
        elif event_type == "error":
            self.vars["status"].set("오류")
            self.append_log(f"오류: {event.get('message')}")
        elif event_type == "resume_requested":
            self.handle_enter_key()
        elif event_type == "delete_requested":
            self.handle_delete_key()
        elif event_type == "insert_requested":
            self.handle_insert_key()
        elif event_type == "manual_overlay_requested":
            self.handle_manual_overlay_key()
        elif event_type == "global_enter_ready":
            self.append_log(str(event.get("message", "")))
        elif event_type == "global_enter_error":
            self.append_log(f"백그라운드 Enter 오류: {event.get('message')}")
        elif event_type == "score_api_result":
            result = event.get("result")
            values = event.get("values")
            if isinstance(result, ScoreApiResult) and isinstance(values, dict):
                self.handle_score_api_result(result, values)
        elif event_type == "score_api_error":
            self.handle_score_api_error(str(event.get("message", "")))
        elif event_type == "record_import_result":
            results = event.get("results", [])
            if isinstance(results, list):
                self.handle_record_import_result(str(event.get("nickname", "")), results)
        elif event_type == "record_import_error":
            self.handle_record_import_error(str(event.get("message", "")))

    def on_canvas_down(self, event: tk.Event) -> None:
        if self.image is None or not self.is_inside_image(event.x, event.y):
            return
        self.update_magnifier(event.x, event.y)
        canvas_x = self.clamp_canvas_x(event.x)
        canvas_y = self.clamp_canvas_y(event.y)
        if self.reassign_box_index is not None:
            self.drag_start = (canvas_x, canvas_y)
            self.drag_current = (canvas_x, canvas_y)
            self.drag_mode = "reassign"
            self.drag_box_index = self.reassign_box_index
            self.canvas.configure(cursor="crosshair")
            return
        hit_index = self.hit_test_box(canvas_x, canvas_y)
        self.drag_start = (canvas_x, canvas_y)
        self.drag_current = (canvas_x, canvas_y)
        if hit_index is not None:
            self.select_box_index(hit_index)
            self.drag_mode = "move"
            self.drag_box_index = hit_index
            self.drag_origin_image = self.canvas_to_image_coords(canvas_x, canvas_y)
            self.drag_origin_box = self.config.manual_boxes[hit_index].normalized()
            self.canvas.configure(cursor="fleur")
            return
        self.drag_mode = "create"
        self.drag_box_index = None
        self.drag_origin_image = None
        self.drag_origin_box = None

    def on_canvas_drag(self, event: tk.Event) -> None:
        if self.drag_start is None or self.image is None:
            return
        canvas_x = self.clamp_canvas_x(event.x)
        canvas_y = self.clamp_canvas_y(event.y)
        self.drag_current = (canvas_x, canvas_y)
        self.update_magnifier(canvas_x, canvas_y)
        if self.drag_mode == "move":
            self.move_active_box(canvas_x, canvas_y)
        self.redraw_canvas()

    def on_canvas_motion(self, event: tk.Event) -> None:
        self.update_magnifier(event.x, event.y)
        if self.image is None or self.drag_mode is not None:
            return
        self.canvas.configure(cursor="fleur" if self.hit_test_box(event.x, event.y) is not None else "crosshair")

    def on_canvas_leave(self, _event: tk.Event) -> None:
        self.clear_magnifier()
        if self.drag_mode is None:
            self.canvas.configure(cursor="crosshair")

    def on_canvas_up(self, event: tk.Event) -> None:
        if self.drag_start is None or self.image is None:
            return
        end = (self.clamp_canvas_x(event.x), self.clamp_canvas_y(event.y))
        start_x, start_y = self.drag_start
        end_x, end_y = end
        mode = self.drag_mode
        self.drag_start = None
        self.drag_current = None
        self.drag_mode = None
        self.drag_box_index = None
        self.drag_origin_image = None
        self.drag_origin_box = None
        self.canvas.configure(cursor="crosshair")

        if mode == "move":
            self.refresh_box_list()
            self.redraw_canvas()
            return

        if mode == "reassign":
            self.finish_box_reassign(start_x, start_y, end_x, end_y)
            return

        if abs(end_x - start_x) < 5 or abs(end_y - start_y) < 5:
            self.redraw_canvas()
            return

        x1, y1 = self.canvas_to_image_coords(start_x, start_y)
        x2, y2 = self.canvas_to_image_coords(end_x, end_y)
        default_name = f"box_{len(self.config.manual_boxes) + 1}"
        name = simpledialog.askstring("박스 이름", "이름", initialvalue=default_name, parent=self.root)
        if name is None:
            self.redraw_canvas()
            return

        box = BoxRegion(name=name.strip() or default_name, x1=x1, y1=y1, x2=x2, y2=y2).normalized()
        self.config.manual_boxes.append(box)
        self.selected_box_index = len(self.config.manual_boxes) - 1
        self.refresh_box_list()
        self.redraw_canvas()

    def redraw_canvas(self) -> None:
        self.canvas.delete("all")
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)

        if self.image is None:
            self.canvas.create_text(
                24,
                24,
                text="이미지를 열거나 설정을 불러오세요.",
                fill="#e4e8ee",
                anchor="nw",
                font=("Malgun Gothic", 14),
            )
            return

        image_w, image_h = self.image.size
        self.scale_ratio = min(width / image_w, height / image_h)
        draw_w = max(1, int(image_w * self.scale_ratio))
        draw_h = max(1, int(image_h * self.scale_ratio))
        self.offset_x = (width - draw_w) // 2
        self.offset_y = (height - draw_h) // 2

        resized = self.image.resize((draw_w, draw_h), RESAMPLE_LANCZOS)
        self.display_photo = ImageTk.PhotoImage(resized)
        self.canvas.create_image(self.offset_x, self.offset_y, anchor="nw", image=self.display_photo)

        trigger_name = str(self.vars["trigger_box_name"].get())
        for index, box in enumerate(self.config.manual_boxes):
            color = "#3ee37d"
            if box.name == trigger_name:
                color = "#ffcc33"
            if index == self.selected_box_index:
                color = "#46a7ff"
            self.draw_box(box.normalized(), color=color, width=3 if index == self.selected_box_index else 2)

        if self.drag_mode in ("create", "reassign") and self.drag_start is not None and self.drag_current is not None:
            self.canvas.create_rectangle(
                self.drag_start[0],
                self.drag_start[1],
                self.drag_current[0],
                self.drag_current[1],
                outline="#ff7a45" if self.drag_mode == "create" else "#ffffff",
                width=2,
                dash=(5, 3),
            )

    def draw_box(self, box: BoxRegion, color: str, width: int) -> None:
        x1 = self.offset_x + int(box.x1 * self.scale_ratio)
        y1 = self.offset_y + int(box.y1 * self.scale_ratio)
        x2 = self.offset_x + int(box.x2 * self.scale_ratio)
        y2 = self.offset_y + int(box.y2 * self.scale_ratio)
        self.canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=width)
        self.canvas.create_text(
            x1 + 4,
            max(4, y1 - 18),
            text=box.name,
            fill=color,
            anchor="nw",
            font=("Malgun Gothic", 10, "bold"),
        )

    def refresh_box_list(self) -> None:
        self.coordinate_variables = {box.name: box.normalized() for box in self.config.manual_boxes}
        numeric_names = set(parse_box_name_list(str(self.vars["numeric_box_names"].get())))
        required_names = set(REQUIRED_BOX_NAMES)
        self.box_list.delete(0, tk.END)
        for index, box in enumerate(self.config.manual_boxes):
            normalized = box.normalized()
            suffixes = []
            if normalized.name in required_names:
                suffixes.append("required")
            if normalized.name in numeric_names:
                suffixes.append("digits")
            suffix = f" [{' / '.join(suffixes)}]" if suffixes else ""
            self.box_list.insert(
                tk.END,
                f"{index + 1}. {normalized.name}{suffix} ({normalized.x1},{normalized.y1})-({normalized.x2},{normalized.y2})",
            )
        current = str(self.vars["trigger_box_name"].get())
        names = [box.name for box in self.config.manual_boxes]
        combo_names = list(names)
        if current and current not in combo_names:
            combo_names.insert(0, current)
        self.trigger_combo["values"] = combo_names
        if names and not current:
            self.vars["trigger_box_name"].set(names[0])
            current = names[0]
        if current:
            self.trigger_combo.set(current)
        self.update_coord_text()

    def on_box_selected(self, _event: tk.Event) -> None:
        selection = self.box_list.curselection()
        self.selected_box_index = int(selection[0]) if selection else None
        self.update_coord_text()
        self.redraw_canvas()

    def select_box_index(self, index: int) -> None:
        if index < 0 or index >= len(self.config.manual_boxes):
            return
        self.selected_box_index = index
        self.box_list.selection_clear(0, tk.END)
        self.box_list.selection_set(index)
        self.box_list.activate(index)
        self.update_coord_text()

    def update_coord_text(self) -> None:
        self.coord_text.configure(state=tk.NORMAL)
        self.coord_text.delete("1.0", tk.END)
        if self.selected_box_index is not None and self.selected_box_index < len(self.config.manual_boxes):
            box = self.config.manual_boxes[self.selected_box_index].normalized()
            self.sync_box_edit_vars(box)
            numeric_names = set(parse_box_name_list(str(self.vars["numeric_box_names"].get())))
            lines = [
                f"name = {box.name}",
                f"required = {box.name in REQUIRED_BOX_NAMES}",
                f"x1 = {box.x1}",
                f"y1 = {box.y1}",
                f"x2 = {box.x2}",
                f"y2 = {box.y2}",
                f"width = {box.width}",
                f"height = {box.height}",
                "ocr_lang = korean",
                f"ocr_filter = {'digits' if box.name in numeric_names else '-'}",
            ]
            self.coord_text.insert(tk.END, "\n".join(lines))
        else:
            self.clear_box_edit_vars()
        self.coord_text.configure(state=tk.DISABLED)

    def sync_box_edit_vars(self, box: BoxRegion) -> None:
        self.box_edit_vars["name"].set(box.name)
        self.box_edit_vars["x1"].set(str(box.x1))
        self.box_edit_vars["y1"].set(str(box.y1))
        self.box_edit_vars["x2"].set(str(box.x2))
        self.box_edit_vars["y2"].set(str(box.y2))

    def clear_box_edit_vars(self) -> None:
        for variable in self.box_edit_vars.values():
            variable.set("")

    def start_box_reassign(self) -> None:
        if self.image is None:
            messagebox.showwarning("이미지 없음", "먼저 이미지를 열거나 설정을 불러오세요.")
            return
        if self.selected_box_index is None or self.selected_box_index >= len(self.config.manual_boxes):
            messagebox.showwarning("박스 선택 없음", "재지정할 박스를 먼저 선택하세요.")
            return
        self.reassign_box_index = self.selected_box_index
        self.drag_start = None
        self.drag_current = None
        self.drag_mode = None
        self.canvas.configure(cursor="crosshair")
        self.append_log(f"박스 재지정 대기: {self.config.manual_boxes[self.reassign_box_index].name}")

    def finish_box_reassign(self, start_x: int, start_y: int, end_x: int, end_y: int) -> None:
        index = self.reassign_box_index
        self.reassign_box_index = None
        if index is None or index >= len(self.config.manual_boxes):
            self.redraw_canvas()
            return
        if abs(end_x - start_x) < 5 or abs(end_y - start_y) < 5:
            self.append_log("박스 재지정 취소")
            self.redraw_canvas()
            return

        x1, y1 = self.canvas_to_image_coords(start_x, start_y)
        x2, y2 = self.canvas_to_image_coords(end_x, end_y)
        old_box = self.config.manual_boxes[index].normalized()
        self.config.manual_boxes[index] = BoxRegion(
            name=old_box.name,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
        ).normalized()
        self.selected_box_index = index
        self.refresh_box_list()
        self.select_box_index(index)
        self.redraw_canvas()
        self.append_log(f"박스 재지정 완료: {old_box.name}")

    def apply_box_edits(self) -> None:
        if self.selected_box_index is None or self.selected_box_index >= len(self.config.manual_boxes):
            return
        try:
            old_box = self.config.manual_boxes[self.selected_box_index].normalized()
            name = str(self.box_edit_vars["name"].get()).strip() or old_box.name
            edited = BoxRegion(
                name=name,
                x1=int(self.box_edit_vars["x1"].get()),
                y1=int(self.box_edit_vars["y1"].get()),
                x2=int(self.box_edit_vars["x2"].get()),
                y2=int(self.box_edit_vars["y2"].get()),
            ).normalized()
        except ValueError:
            messagebox.showerror("좌표 오류", "x1, y1, x2, y2는 정수로 입력하세요.")
            return

        if edited.width <= 0 or edited.height <= 0:
            messagebox.showerror("좌표 오류", "박스 너비와 높이는 1 이상이어야 합니다.")
            return
        if self.image is not None:
            image_w, image_h = self.image.size
            if edited.x1 < 0 or edited.y1 < 0 or edited.x2 > image_w or edited.y2 > image_h:
                messagebox.showerror("좌표 오류", f"좌표는 이미지 범위 0,0 - {image_w},{image_h} 안에 있어야 합니다.")
                return

        if str(self.vars["trigger_box_name"].get()) == old_box.name:
            self.vars["trigger_box_name"].set(edited.name)
        self.config.manual_boxes[self.selected_box_index] = edited
        self.refresh_box_list()
        self.select_box_index(self.selected_box_index)
        self.redraw_canvas()

    def delete_selected_box(self) -> None:
        if self.selected_box_index is None:
            return
        if self.selected_box_index < len(self.config.manual_boxes):
            deleted = self.config.manual_boxes.pop(self.selected_box_index)
            self.append_log(f"박스 삭제: {deleted.name}")
        self.selected_box_index = None
        self.refresh_box_list()
        self.redraw_canvas()

    def clear_boxes(self) -> None:
        self.config.manual_boxes.clear()
        self.selected_box_index = None
        self.refresh_box_list()
        self.redraw_canvas()

    def find_box(self, name: str) -> BoxRegion | None:
        for box in self.config.manual_boxes:
            if box.name == name:
                return box.normalized()
        return None

    def hit_test_box(self, canvas_x: int, canvas_y: int) -> int | None:
        if self.image is None or not self.is_inside_image(canvas_x, canvas_y):
            return None
        image_x, image_y = self.canvas_to_image_coords(canvas_x, canvas_y)
        for index in range(len(self.config.manual_boxes) - 1, -1, -1):
            box = self.config.manual_boxes[index].normalized()
            if box.x1 <= image_x <= box.x2 and box.y1 <= image_y <= box.y2:
                return index
        return None

    def move_active_box(self, canvas_x: int, canvas_y: int) -> None:
        if (
            self.image is None
            or self.drag_box_index is None
            or self.drag_origin_image is None
            or self.drag_origin_box is None
            or self.drag_box_index >= len(self.config.manual_boxes)
        ):
            return

        image_x, image_y = self.canvas_to_image_coords(canvas_x, canvas_y)
        origin_x, origin_y = self.drag_origin_image
        dx = image_x - origin_x
        dy = image_y - origin_y

        original = self.drag_origin_box
        image_w, image_h = self.image.size
        width = original.width
        height = original.height
        max_left = max(0, image_w - width)
        max_top = max(0, image_h - height)
        left = max(0, min(original.x1 + dx, max_left))
        top = max(0, min(original.y1 + dy, max_top))
        self.config.manual_boxes[self.drag_box_index] = BoxRegion(
            name=original.name,
            x1=left,
            y1=top,
            x2=min(image_w, left + width),
            y2=min(image_h, top + height),
        ).normalized()
        self.update_coord_text()

    def is_inside_image(self, x: int, y: int) -> bool:
        if self.image is None:
            return False
        right = self.offset_x + int(self.image.size[0] * self.scale_ratio)
        bottom = self.offset_y + int(self.image.size[1] * self.scale_ratio)
        return self.offset_x <= x <= right and self.offset_y <= y <= bottom

    def clamp_canvas_x(self, x: int) -> int:
        if self.image is None:
            return x
        left = self.offset_x
        right = self.offset_x + int(self.image.size[0] * self.scale_ratio)
        return max(left, min(x, right))

    def clamp_canvas_y(self, y: int) -> int:
        if self.image is None:
            return y
        top = self.offset_y
        bottom = self.offset_y + int(self.image.size[1] * self.scale_ratio)
        return max(top, min(y, bottom))

    def canvas_to_image_coords(self, x: int, y: int) -> tuple[int, int]:
        if self.image is None:
            return 0, 0
        image_x = int((x - self.offset_x) / self.scale_ratio)
        image_y = int((y - self.offset_y) / self.scale_ratio)
        image_w, image_h = self.image.size
        return max(0, min(image_x, image_w)), max(0, min(image_y, image_h))

    def update_magnifier(self, canvas_x: int, canvas_y: int) -> None:
        if self.image is None or not self.is_inside_image(canvas_x, canvas_y):
            self.clear_magnifier()
            return

        image_x, image_y = self.canvas_to_image_coords(canvas_x, canvas_y)
        image_w, image_h = self.image.size
        radius = self.magnifier_radius
        left = max(0, image_x - radius)
        top = max(0, image_y - radius)
        right = min(image_w, image_x + radius + 1)
        bottom = min(image_h, image_y + radius + 1)

        sample = Image.new("RGB", (radius * 2 + 1, radius * 2 + 1), "#111820")
        crop = self.image.crop((left, top, right, bottom))
        paste_x = left - (image_x - radius)
        paste_y = top - (image_y - radius)
        sample.paste(crop, (paste_x, paste_y))

        zoomed_size = sample.width * self.magnifier_zoom
        zoomed = sample.resize((zoomed_size, zoomed_size), Image.Resampling.NEAREST)
        self.magnifier_photo = ImageTk.PhotoImage(zoomed)

        self.magnifier_canvas.delete("all")
        self.magnifier_canvas.create_image(0, 0, anchor="nw", image=self.magnifier_photo)

        center = radius * self.magnifier_zoom
        size = zoomed_size
        self.magnifier_canvas.create_line(center, 0, center, size, fill="#ffcc33", width=1)
        self.magnifier_canvas.create_line(0, center, size, center, fill="#ffcc33", width=1)
        self.magnifier_canvas.create_rectangle(
            center,
            center,
            center + self.magnifier_zoom,
            center + self.magnifier_zoom,
            outline="#46a7ff",
            width=2,
        )
        pixel = self.image.getpixel((min(image_x, image_w - 1), min(image_y, image_h - 1)))
        self.magnifier_label.config(text=f"x={image_x}, y={image_y}, rgb={pixel}")

    def clear_magnifier(self) -> None:
        if not hasattr(self, "magnifier_canvas"):
            return
        self.magnifier_canvas.delete("all")
        self.magnifier_canvas.create_text(
            10,
            10,
            text="이미지 위에 커서를 올리세요.",
            fill="#d8dee9",
            anchor="nw",
            font=("Malgun Gothic", 9),
        )
        self.magnifier_label.config(text="x=-, y=-")

    def append_log(self, message: str) -> None:
        message = self._shorten_paths_in_message(message)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)

    @staticmethod
    def _shorten_paths_in_message(message: Any) -> str:
        text = str(message)
        for base in (APP_DIR, DEFAULT_DEBUG_DIR, DEFAULT_OUTPUT_DIR):
            base_text = str(base)
            text = text.replace(base_text + "\\", "")
            text = text.replace(base_text + "/", "")
            if text == base_text:
                text = base.name

        def quoted_replacement(match: re.Match[str]) -> str:
            quote = match.group(1)
            path_text = match.group(2)
            return f"{quote}{Path(path_text).name or path_text}{quote}"

        text = re.sub(r"(['\"])([A-Za-z]:\\[^'\"]+)(['\"])", quoted_replacement, text)
        return re.sub(
            r"(?<![\w])([A-Za-z]:\\[^\s:]+(?:\\[^\s:]+)+)",
            lambda match: Path(match.group(1)).name or match.group(1),
            text,
        )

    def on_close(self) -> None:
        if self.registration_overlay is not None:
            self.registration_overlay.close_now()
            self.registration_overlay = None
        if self.message_overlay is not None:
            self.message_overlay.close_now()
            self.message_overlay = None
        self.stop_monitor()
        if self.global_enter_listener is not None:
            self.global_enter_listener.stop()
            self.global_enter_listener.join(timeout=0.5)
        self.root.destroy()
