from __future__ import annotations

import tempfile
import traceback
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .boxes import BoxRegion
from .config import OCRSettings
from .constants import (
    PADDLE_OCR_DET_MODEL_NAME,
    PADDLE_OCR_LANG,
    PADDLE_OCR_MODEL_CACHE_DIR,
    PADDLE_OCR_REC_MODEL_NAME,
    RESAMPLE_LANCZOS,
)

PaddleOCRClass: Any | None = None
REQUIRED_MODEL_FILES = ("config.json", "inference.json", "inference.pdiparams", "inference.yml")

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]


class OCRService:
    def __init__(self, settings: OCRSettings) -> None:
        self.settings = settings
        self._engine: Any | None = None
        self.apply_settings(settings)

    def apply_settings(self, settings: OCRSettings) -> None:
        if getattr(self, "settings", None) != settings:
            self._engine = None
        self.settings = settings

    def prepare_model(self) -> bool:
        missing_before = self.missing_required_model_names()
        self._get_engine()
        return bool(missing_before)

    @classmethod
    def missing_required_model_names(cls) -> list[str]:
        return [
            model_name
            for model_name in (PADDLE_OCR_DET_MODEL_NAME, PADDLE_OCR_REC_MODEL_NAME)
            if not cls._is_model_ready(model_name)
        ]

    @staticmethod
    def _is_model_ready(model_name: str) -> bool:
        model_dir = PADDLE_OCR_MODEL_CACHE_DIR / model_name
        return model_dir.is_dir() and all((model_dir / filename).is_file() for filename in REQUIRED_MODEL_FILES)

    def preprocess(self, image: Image.Image, mode: str = "default") -> Image.Image:
        if mode == "break_outline":
            return self.preprocess_break_outline(image)
        processed = image.copy()
        if self.settings.grayscale:
            processed = ImageOps.grayscale(processed)
        if self.settings.threshold:
            if processed.mode != "L":
                processed = ImageOps.grayscale(processed)
            cutoff = max(0, min(255, int(self.settings.threshold_value)))
            processed = processed.point(lambda value: 0 if value < cutoff else 255, mode="1")
        return processed

    def preprocess_break_outline(self, image: Image.Image) -> Image.Image:
        processed = image.convert("L")
        scale = 4
        processed = processed.resize((max(1, processed.width * scale), max(1, processed.height * scale)), RESAMPLE_LANCZOS)
        processed = ImageOps.autocontrast(processed)
        processed = ImageEnhance.Contrast(processed).enhance(3.5)
        processed = ImageEnhance.Sharpness(processed).enhance(2.0)
        outline = processed.filter(ImageFilter.FIND_EDGES)
        outline = ImageOps.autocontrast(outline)
        outline = outline.filter(ImageFilter.MaxFilter(3))
        return outline.point(lambda value: 0 if value >= 28 else 255, mode="L")

    def image_to_string(
        self,
        image: Image.Image,
        preprocess_mode: str = "default",
        char_whitelist: str | None = None,
    ) -> str:
        processed = self.preprocess(image, mode=preprocess_mode).convert("RGB")
        min_confidence = max(0.0, min(1.0, float(self.settings.min_confidence)))
        raw_result = self._predict(processed)
        items = self._extract_text_items(raw_result, min_confidence)
        text, _score = self._format_text_items(items, char_whitelist)
        return text.strip()

    def run_regions(
        self,
        screenshot: Image.Image,
        boxes: list[BoxRegion],
        numeric_box_names: set[str] | None = None,
        score_outline_ocr: bool = True,
    ) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        numeric_box_names = numeric_box_names or set()
        for box in boxes:
            normalized = box.normalized()
            is_numeric = normalized.name in numeric_box_names
            ocr_preprocess = "default"
            retry_error = ""
            try:
                cropped = normalized.crop(screenshot)
                if normalized.name == "Score" and score_outline_ocr:
                    text = self.image_to_string(
                        cropped,
                        preprocess_mode="break_outline",
                        char_whitelist="0123456789",
                    )
                    ocr_preprocess = "break_outline"
                else:
                    text = self.image_to_string(
                        cropped,
                        char_whitelist="0123456789" if is_numeric else None,
                    )
                if normalized.name == "BREAK" and not self._has_digit(text):
                    try:
                        retry_text = self.image_to_string(
                            cropped,
                            preprocess_mode="break_outline",
                            char_whitelist="0123456789",
                        )
                        if retry_text:
                            text = retry_text
                            ocr_preprocess = "break_outline"
                    except Exception as exc:
                        retry_error = str(exc)
                error = ""
            except Exception as exc:
                text = ""
                error = str(exc)
            results.append(
                {
                    "name": normalized.name,
                    "coords": f"{normalized.x1},{normalized.y1},{normalized.x2},{normalized.y2}",
                    "ocr_engine": "PaddleOCR",
                    "ocr_lang": PADDLE_OCR_LANG,
                    "ocr_filter": "digits" if is_numeric else "",
                    "ocr_preprocess": ocr_preprocess,
                    "text": text,
                    "error": error,
                    "retry_error": retry_error,
                }
            )
        return results

    def _get_engine(self) -> Any:
        paddle_ocr = self._get_paddle_ocr_class()
        if self._engine is not None:
            return self._engine

        try:
            engine = paddle_ocr(
                text_detection_model_name=PADDLE_OCR_DET_MODEL_NAME,
                text_recognition_model_name=PADDLE_OCR_REC_MODEL_NAME,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        except TypeError:
            engine = paddle_ocr(
                lang=PADDLE_OCR_LANG,
                use_angle_cls=False,
            )
        except Exception as exc:
            raise RuntimeError(self._format_engine_error(exc)) from exc
        self._engine = engine
        return engine

    @staticmethod
    def _format_engine_error(exc: BaseException) -> str:
        messages = [str(exc).strip() or exc.__class__.__name__]
        cause = exc.__cause__ or exc.__context__
        while cause is not None:
            text = str(cause).strip() or cause.__class__.__name__
            messages.append(f"{cause.__class__.__name__}: {text}")
            cause = cause.__cause__ or cause.__context__
        detail = " / ".join(message for message in messages if message)
        traceback_tail = "".join(traceback.format_exception_only(exc.__class__, exc)).strip()
        if traceback_tail and traceback_tail not in detail:
            detail = f"{detail} / {traceback_tail}"
        return f"PaddleOCR 한국어 모델 초기화 실패: {detail}"

    @staticmethod
    def _get_paddle_ocr_class() -> Any:
        global PaddleOCRClass
        if PaddleOCRClass is not None:
            return PaddleOCRClass
        try:
            from paddleocr import PaddleOCR as loaded_paddle_ocr
        except ImportError as exc:
            raise RuntimeError("paddleocr is not installed. Install with: py -3.13 -m pip install paddleocr") from exc
        PaddleOCRClass = loaded_paddle_ocr
        return PaddleOCRClass

    def _predict(self, image: Image.Image) -> Any:
        engine = self._get_engine()
        image_array = np.array(image) if np is not None else None

        if image_array is not None and hasattr(engine, "predict"):
            try:
                return list(engine.predict(image_array))
            except Exception:
                pass
        if image_array is not None and hasattr(engine, "ocr"):
            try:
                return engine.ocr(image_array, cls=False)
            except TypeError:
                return engine.ocr(image_array)

        temp_path = self._save_temp_image(image)
        try:
            if hasattr(engine, "predict"):
                return list(engine.predict(str(temp_path)))
            if hasattr(engine, "ocr"):
                try:
                    return engine.ocr(str(temp_path), cls=False)
                except TypeError:
                    return engine.ocr(str(temp_path))
        finally:
            temp_path.unlink(missing_ok=True)
        raise RuntimeError("Unsupported PaddleOCR engine interface.")

    @staticmethod
    def _save_temp_image(image: Image.Image) -> Path:
        handle = tempfile.NamedTemporaryFile(prefix="maxocr_", suffix=".png", delete=False)
        path = Path(handle.name)
        handle.close()
        image.save(path)
        return path

    def _extract_text_items(self, raw_result: Any, min_confidence: float) -> list[tuple[str, float]]:
        collected: list[tuple[str, float]] = []
        self._walk_result(raw_result, collected, min_confidence)
        return collected

    def _walk_result(self, obj: Any, collected: list[tuple[str, float]], min_confidence: float) -> None:
        if obj is None:
            return
        result_json = getattr(obj, "json", None)
        if isinstance(result_json, dict):
            self._walk_result(result_json, collected, min_confidence)
            return
        if callable(result_json):
            try:
                self._walk_result(result_json(), collected, min_confidence)
                return
            except Exception:
                pass

        if isinstance(obj, dict):
            data = obj.get("res", obj)
            rec_texts = data.get("rec_texts") if isinstance(data, dict) else None
            rec_scores = data.get("rec_scores") if isinstance(data, dict) else None
            if isinstance(rec_texts, list):
                for index, text in enumerate(rec_texts):
                    score = 1.0
                    if isinstance(rec_scores, list) and index < len(rec_scores):
                        score = self._safe_score(rec_scores[index])
                    self._append_text_item(collected, text, score, min_confidence)
                return

            text = data.get("rec_text") if isinstance(data, dict) else None
            if text is not None:
                self._append_text_item(collected, text, self._safe_score(data.get("rec_score", 1.0)), min_confidence)

            for key in ("text", "label", "content"):
                value = data.get(key) if isinstance(data, dict) else None
                if isinstance(value, str):
                    self._append_text_item(collected, value, 1.0, min_confidence)

            if isinstance(data, dict):
                for value in data.values():
                    self._walk_result(value, collected, min_confidence)
            return

        if isinstance(obj, (list, tuple)):
            if self._looks_like_v2_line(obj):
                text, score = obj[1][0], self._safe_score(obj[1][1])
                self._append_text_item(collected, text, score, min_confidence)
                return
            for item in obj:
                self._walk_result(item, collected, min_confidence)

    @staticmethod
    def _looks_like_v2_line(obj: Any) -> bool:
        return (
            isinstance(obj, (list, tuple))
            and len(obj) >= 2
            and isinstance(obj[1], (list, tuple))
            and len(obj[1]) >= 2
            and isinstance(obj[1][0], str)
        )

    @staticmethod
    def _append_text_item(collected: list[tuple[str, float]], text: Any, score: float, min_confidence: float) -> None:
        value = str(text).strip()
        if value and score >= min_confidence:
            collected.append((value, score))

    @staticmethod
    def _safe_score(value: Any) -> float:
        try:
            return float(value)
        except Exception:
            return 1.0

    @staticmethod
    def _format_text_items(items: Iterable[tuple[str, float]], char_whitelist: str | None) -> tuple[str, float]:
        item_list = list(items)
        if not item_list:
            return "", 0.0
        if char_whitelist:
            allowed = set(char_whitelist)
            filtered = ["".join(char for char in text if char in allowed) for text, _score in item_list]
            text = "".join(part for part in filtered if part)
        else:
            text = "\n".join(text for text, _score in item_list if text).strip()
        scores = [score for _text, score in item_list]
        mean_score = sum(scores) / max(1, len(scores))
        return text.strip(), mean_score

    @staticmethod
    def _has_digit(text: str) -> bool:
        return any(char.isdigit() for char in str(text))
