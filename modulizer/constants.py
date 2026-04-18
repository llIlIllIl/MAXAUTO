from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment]

APP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = APP_DIR / "OCR.json"
DEFAULT_TEMPLATE_PATH = APP_DIR / "F5.png"
DEFAULT_TITLE_DAT_PATH = APP_DIR / "title.dat"
DEFAULT_OUTPUT_DIR = APP_DIR / "output"
DEFAULT_DEBUG_DIR = APP_DIR / "Debug"
DEFAULT_MATCH_THRESHOLD = 0.985
RESAMPLE_LANCZOS = 1 if Image is None else getattr(getattr(Image, "Resampling", Image), "LANCZOS")
PADDLE_OCR_LANG = "korean"
LEGACY_BOX_NAME_MAP = {"F5": "Button"}
REQUIRED_BOX_NAMES = ("Title", "BREAK", "Score", "Button", "difficult")
