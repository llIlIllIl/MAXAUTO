from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .boxes import BoxRegion
from .constants import (
    DEFAULT_MATCH_THRESHOLD,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_TEMPLATE_PATH,
    LEGACY_BOX_NAME_MAP,
    REQUIRED_BOX_NAMES,
)

OVERLAY_BACKEND_DESKTOP = "desktop"
OVERLAY_BACKEND_HUDHOOK_BRIDGE = "hudhook_bridge"
OVERLAY_BACKEND_GAME_OVERLAY_SDK = OVERLAY_BACKEND_HUDHOOK_BRIDGE
OVERLAY_BACKEND_PYTHON_EXCLUSIVE_COMPAT = "python_exclusive_compat"
DEFAULT_GAME_OVERLAY_TARGET_PROCESS = "DJMAX RESPECT V.exe"
DEFAULT_GAME_OVERLAY_STEAM_APP_ID = 960170
DEFAULT_GAME_OVERLAY_ATTACH_STRATEGY = "run_process_if_path_else_monitor"
DEFAULT_STREAMER_HOST_PORT = 8765
VALID_OVERLAY_BACKENDS = {
    OVERLAY_BACKEND_DESKTOP,
    OVERLAY_BACKEND_HUDHOOK_BRIDGE,
}
LEGACY_OVERLAY_BACKENDS = {
    OVERLAY_BACKEND_PYTHON_EXCLUSIVE_COMPAT: OVERLAY_BACKEND_GAME_OVERLAY_SDK,
    "game_overlay_sdk": OVERLAY_BACKEND_GAME_OVERLAY_SDK,
}


def parse_box_name_list(value: Any) -> list[str]:
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        items = value.split(",")
    else:
        items = []
    return [str(item).strip() for item in items if str(item).strip()]


def find_missing_required_boxes(boxes: list[BoxRegion]) -> list[str]:
    valid_names = {
        box.normalized().name
        for box in boxes
        if box.normalized().width > 0 and box.normalized().height > 0
    }
    return [name for name in REQUIRED_BOX_NAMES if name not in valid_names]


def normalize_box_name(name: str) -> str:
    clean_name = str(name).strip()
    return LEGACY_BOX_NAME_MAP.get(clean_name, clean_name)


def normalize_overlay_backend(value: Any) -> str:
    backend = str(value or "").strip()
    backend = LEGACY_OVERLAY_BACKENDS.get(backend, backend)
    if backend in VALID_OVERLAY_BACKENDS:
        return backend
    return OVERLAY_BACKEND_DESKTOP


@dataclass
class OCRSettings:
    min_confidence: float = 0.0
    grayscale: bool = False
    threshold: bool = False
    threshold_value: int = 140


@dataclass
class MonitorSettings:
    trigger_box_name: str = "Button"
    template_path: str = str(DEFAULT_TEMPLATE_PATH) if DEFAULT_TEMPLATE_PATH.exists() else ""
    output_dir: str = str(DEFAULT_OUTPUT_DIR)
    interval_ms: int = 500
    match_threshold: float = DEFAULT_MATCH_THRESHOLD
    numeric_box_names: list[str] = field(default_factory=lambda: ["Score", "CLASS_NUM"])
    overlay_timeout_seconds: int = 10
    message_overlay_timeout_seconds: int = 10
    compare_button_record: bool = True
    save_screenshot: bool = True
    pause_after_detection: bool = True
    include_trigger_box_in_ocr: bool = False
    score_outline_ocr: bool = True
    record_import_nickname: str = ""
    overlay_backend: str = OVERLAY_BACKEND_DESKTOP
    python_exclusive_warning_accepted: bool = False
    python_exclusive_click_through: bool = False
    python_exclusive_focus_safe: bool = True
    game_overlay_target_process: str = DEFAULT_GAME_OVERLAY_TARGET_PROCESS
    game_overlay_steam_app_id: int = DEFAULT_GAME_OVERLAY_STEAM_APP_ID
    game_overlay_exe_path: str = ""
    game_overlay_attach_strategy: str = DEFAULT_GAME_OVERLAY_ATTACH_STRATEGY
    game_overlay_warning_accepted: bool = False
    game_overlay_warning_version: int = 0
    streamer_host_enabled: bool = False
    streamer_username: str = ""
    streamer_button: str = ""
    streamer_host_port: int = DEFAULT_STREAMER_HOST_PORT


@dataclass
class AppConfig:
    image_path: str = ""
    ocr_settings: OCRSettings = field(default_factory=OCRSettings)
    monitor_settings: MonitorSettings = field(default_factory=MonitorSettings)
    manual_boxes: list[BoxRegion] = field(default_factory=list)


class ConfigStore:
    @staticmethod
    def load(path: Path) -> AppConfig:
        with path.open("r", encoding="utf-8") as file:
            raw = json.load(file)

        ocr_raw = raw.get("ocr_settings", {})
        monitor_raw = raw.get("monitor_settings", {})
        boxes: list[BoxRegion] = []
        raw_boxes = raw.get("manual_boxes", [])
        raw_box_names = {str(box.get("name", "")).strip() for box in raw_boxes if isinstance(box, dict)}
        has_new_button_box = "Button" in raw_box_names
        for index, box in enumerate(raw_boxes, start=1):
            try:
                box_name = str(box.get("name") or f"box_{index}")
                if not (has_new_button_box and box_name.strip() in LEGACY_BOX_NAME_MAP):
                    box_name = normalize_box_name(box_name)
                boxes.append(
                    BoxRegion(
                        name=box_name,
                        x1=int(box["x1"]),
                        y1=int(box["y1"]),
                        x2=int(box["x2"]),
                        y2=int(box["y2"]),
                    ).normalized()
                )
            except (KeyError, TypeError, ValueError):
                continue

        return AppConfig(
            image_path=str(raw.get("image_path") or ""),
            ocr_settings=OCRSettings(
                min_confidence=float(ocr_raw.get("min_confidence", 0.0)),
                grayscale=bool(ocr_raw.get("grayscale", False)),
                threshold=bool(ocr_raw.get("threshold", False)),
                threshold_value=int(ocr_raw.get("threshold_value", 140)),
            ),
            monitor_settings=MonitorSettings(
                trigger_box_name=str(monitor_raw.get("trigger_box_name", "Button")).strip() or "Button",
                template_path=str(
                    monitor_raw.get(
                        "template_path",
                        str(DEFAULT_TEMPLATE_PATH) if DEFAULT_TEMPLATE_PATH.exists() else "",
                    )
                ),
                output_dir=str(monitor_raw.get("output_dir", str(DEFAULT_OUTPUT_DIR))),
                interval_ms=int(monitor_raw.get("interval_ms", 500)),
                match_threshold=float(monitor_raw.get("match_threshold", DEFAULT_MATCH_THRESHOLD)),
                numeric_box_names=parse_box_name_list(
                    monitor_raw.get("numeric_box_names", ["Score", "CLASS_NUM"])
                ),
                overlay_timeout_seconds=int(monitor_raw.get("overlay_timeout_seconds", 10)),
                message_overlay_timeout_seconds=int(
                    monitor_raw.get(
                        "message_overlay_timeout_seconds",
                        monitor_raw.get("overlay_timeout_seconds", 10),
                    )
                ),
                compare_button_record=bool(monitor_raw.get("compare_button_record", True)),
                save_screenshot=bool(monitor_raw.get("save_screenshot", True)),
                pause_after_detection=bool(monitor_raw.get("pause_after_detection", True)),
                include_trigger_box_in_ocr=bool(monitor_raw.get("include_trigger_box_in_ocr", False)),
                score_outline_ocr=bool(monitor_raw.get("score_outline_ocr", True)),
                record_import_nickname=str(monitor_raw.get("record_import_nickname", "")).strip(),
                overlay_backend=normalize_overlay_backend(monitor_raw.get("overlay_backend", OVERLAY_BACKEND_DESKTOP)),
                python_exclusive_warning_accepted=bool(
                    monitor_raw.get("python_exclusive_warning_accepted", False)
                ),
                python_exclusive_click_through=bool(monitor_raw.get("python_exclusive_click_through", False)),
                python_exclusive_focus_safe=bool(monitor_raw.get("python_exclusive_focus_safe", True)),
                game_overlay_target_process=str(
                    monitor_raw.get("game_overlay_target_process", DEFAULT_GAME_OVERLAY_TARGET_PROCESS)
                    or DEFAULT_GAME_OVERLAY_TARGET_PROCESS
                ).strip(),
                game_overlay_steam_app_id=int(
                    monitor_raw.get("game_overlay_steam_app_id", DEFAULT_GAME_OVERLAY_STEAM_APP_ID)
                    or DEFAULT_GAME_OVERLAY_STEAM_APP_ID
                ),
                game_overlay_exe_path=str(monitor_raw.get("game_overlay_exe_path", "") or "").strip(),
                game_overlay_attach_strategy=str(
                    monitor_raw.get("game_overlay_attach_strategy", DEFAULT_GAME_OVERLAY_ATTACH_STRATEGY)
                    or DEFAULT_GAME_OVERLAY_ATTACH_STRATEGY
                ).strip(),
                game_overlay_warning_accepted=bool(monitor_raw.get("game_overlay_warning_accepted", False)),
                game_overlay_warning_version=int(monitor_raw.get("game_overlay_warning_version", 0) or 0),
                streamer_host_enabled=bool(
                    monitor_raw.get(
                        "streamer_host_enabled",
                        monitor_raw.get("v_archive_host_enabled", False),
                    )
                ),
                streamer_username=str(
                    monitor_raw.get("streamer_username", monitor_raw.get("v_archive_username", "")) or ""
                ).strip(),
                streamer_button=str(
                    monitor_raw.get("streamer_button", monitor_raw.get("v_archive_button", "")) or ""
                ).strip(),
                streamer_host_port=int(
                    monitor_raw.get("streamer_host_port", DEFAULT_STREAMER_HOST_PORT)
                    or DEFAULT_STREAMER_HOST_PORT
                ),
            ),
            manual_boxes=boxes,
        )

    @staticmethod
    def save(path: Path, config: AppConfig) -> None:
        data = {
            "image_path": config.image_path,
            "ocr_settings": asdict(config.ocr_settings),
            "monitor_settings": asdict(config.monitor_settings),
            "manual_boxes": [asdict(box.normalized()) for box in config.manual_boxes],
        }
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
