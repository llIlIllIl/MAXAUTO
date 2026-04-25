from __future__ import annotations

from pathlib import Path
import sys

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment]

APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = APP_DIR / "OCR.json"
DEFAULT_TEMPLATE_PATH = APP_DIR / "F5.png"
DEFAULT_TITLE_DAT_PATH = APP_DIR / "title.dat"
DEFAULT_OUTPUT_DIR = APP_DIR / "output"
DEFAULT_DEBUG_DIR = APP_DIR / "Debug"
DEFAULT_MATCH_THRESHOLD = 0.985
RESAMPLE_LANCZOS = 1 if Image is None else getattr(getattr(Image, "Resampling", Image), "LANCZOS")
PADDLE_OCR_LANG = "korean"
PADDLE_OCR_DET_MODEL_NAME = "PP-OCRv5_server_det"
PADDLE_OCR_REC_MODEL_NAME = "korean_PP-OCRv5_mobile_rec"
PADDLE_OCR_MODEL_CACHE_DIR = Path.home() / ".paddlex" / "official_models"
LEGACY_BOX_NAME_MAP = {"F5": "Button"}
REQUIRED_BOX_NAMES = ("Title", "BREAK", "Score", "Button", "difficult")
CLI_ARG_DEBUG = "--debug"
CLI_ARG_AUTOSTART_MONITOR = "--autostart-monitor"
CLI_ARG_AUTOSTART_MONITOR_WITH_GAME = "--autostart-monitor-with-game"
CLI_ARG_SKIP_GAME_OVERLAY_WARNING_ONCE = "--skip-game-overlay-warning-once"
CLI_ARG_GAME_OVERLAY_HELPER = "--game-overlay-helper"
CLI_ARG_GAME_OVERLAY_HELPER_SETTINGS = "--game-overlay-helper-settings"
CLI_ARG_GAME_OVERLAY_HELPER_RESPONSE = "--game-overlay-helper-response"
CLI_ARG_GAME_OVERLAY_HELPER_COMMAND = "--game-overlay-helper-command"
CLI_ARG_GAME_OVERLAY_HELPER_PARENT_PID = "--game-overlay-helper-parent-pid"
