from __future__ import annotations

import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageGrab

from .boxes import BoxRegion
from .config import AppConfig
from .ocr_service import OCRService
from .template_matcher import TemplateMatcher
from .title_catalog import TitleCatalog


class MonitorWorker(threading.Thread):
    def __init__(self, config: AppConfig, boxes: list[BoxRegion], event_queue: queue.Queue[dict[str, Any]]) -> None:
        super().__init__(daemon=True)
        self.config = config
        self.boxes = [box.normalized() for box in boxes]
        self.event_queue = event_queue
        self.stop_event = threading.Event()
        self.resume_event = threading.Event()
        self.resume_event.set()
        self.matcher = TemplateMatcher(config.monitor_settings.template_path)
        self.ocr = OCRService(config.ocr_settings)
        self.title_catalog = TitleCatalog()

    def stop(self) -> None:
        self.stop_event.set()
        self.resume_event.set()

    def resume(self) -> None:
        self.resume_event.set()

    def recognize_once(self) -> None:
        try:
            trigger_box = self._find_trigger_box(self.config.monitor_settings.trigger_box_name)
            if trigger_box is None:
                raise RuntimeError(f"Trigger box '{self.config.monitor_settings.trigger_box_name}' was not found.")
            screenshot = ImageGrab.grab().convert("RGB")
            score = self.matcher.compare(trigger_box.crop(screenshot))
            self.event_queue.put({"type": "score", "score": score})
            self._handle_detection(screenshot, trigger_box, score)
        except Exception as exc:
            self.event_queue.put({"type": "error", "message": str(exc)})

    def run(self) -> None:
        try:
            self._run_loop()
        except Exception as exc:
            self.event_queue.put({"type": "error", "message": str(exc)})

    def _run_loop(self) -> None:
        monitor = self.config.monitor_settings
        trigger_box = self._find_trigger_box(monitor.trigger_box_name)
        if trigger_box is None:
            raise RuntimeError(f"Trigger box '{monitor.trigger_box_name}' was not found.")
        if self.matcher.template is None:
            raise RuntimeError("Trigger template image was not found.")

        interval = max(100, int(monitor.interval_ms)) / 1000.0
        threshold = max(0.0, min(1.0, float(monitor.match_threshold)))
        self.event_queue.put({"type": "status", "message": "감시 시작"})

        while not self.stop_event.is_set():
            self.resume_event.wait()
            if self.stop_event.is_set():
                break
            try:
                screenshot = ImageGrab.grab().convert("RGB")
                score = self.matcher.compare(trigger_box.crop(screenshot))
                self.event_queue.put({"type": "score", "score": score})
                if score >= threshold:
                    self._handle_detection(screenshot, trigger_box, score)
                    if monitor.pause_after_detection:
                        self.resume_event.clear()
                        self.event_queue.put({"type": "paused", "message": "감지 후 일시정지"})
            except Exception as exc:
                self.event_queue.put({"type": "error", "message": str(exc)})
                time.sleep(1.0)
            time.sleep(interval)

        self.event_queue.put({"type": "status", "message": "감시 중지"})

    def _find_trigger_box(self, name: str) -> BoxRegion | None:
        for box in self.boxes:
            if box.name == name:
                return box
        return self.boxes[0] if self.boxes else None

    def _handle_detection(self, screenshot: Image.Image, trigger_box: BoxRegion, score: float) -> None:
        monitor = self.config.monitor_settings
        output_dir = Path(monitor.output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = ""
        if monitor.save_screenshot:
            screenshot_path = str(output_dir / f"capture_{timestamp}.png")
            screenshot.save(screenshot_path)

        ocr_boxes = self.boxes
        if not monitor.include_trigger_box_in_ocr:
            ocr_boxes = [box for box in self.boxes if box.name != trigger_box.name]
        results = self.ocr.run_regions(
            screenshot,
            ocr_boxes,
            numeric_box_names=set(monitor.numeric_box_names),
            score_outline_ocr=monitor.score_outline_ocr,
        )
        self._resolve_title_result(results)

        text_path = output_dir / f"ocr_{timestamp}.txt"
        self._write_text_report(text_path, screenshot, trigger_box, score, screenshot_path, results)
        self.event_queue.put(
            {
                "type": "detected",
                "score": score,
                "timestamp": timestamp,
                "trigger_box_name": trigger_box.name,
                "text_path": str(text_path),
                "screenshot_path": screenshot_path,
                "results": results,
                "debug_crops": self._make_debug_crops(screenshot, ("Title", "BREAK", "Score")),
            }
        )

    def _make_debug_crops(self, screenshot: Image.Image, names: tuple[str, ...]) -> dict[str, Image.Image]:
        targets = set(names)
        crops: dict[str, Image.Image] = {}
        for box in self.boxes:
            normalized = box.normalized()
            if normalized.name not in targets:
                continue
            try:
                crops[normalized.name] = normalized.crop(screenshot).copy()
            except Exception:
                pass
        return crops

    def _resolve_title_result(self, results: list[dict[str, str]]) -> None:
        for item in results:
            if item.get("name") != "Title" or item.get("error"):
                continue
            original_text = item.get("text", "")
            resolution = self.title_catalog.resolve(original_text)
            if resolution is None:
                return
            item["raw_text"] = original_text
            item["text"] = resolution.title
            item["title_match_mode"] = resolution.mode
            item["title_match_score"] = f"{resolution.score:.4f}"
            return

    @staticmethod
    def _write_text_report(
        path: Path,
        screenshot: Image.Image,
        trigger_box: BoxRegion,
        score: float,
        screenshot_path: str,
        results: list[dict[str, str]],
    ) -> None:
        lines = [
            f"created_at: {datetime.now().isoformat(timespec='seconds')}",
            f"screen_size: {screenshot.size[0]}x{screenshot.size[1]}",
            f"trigger_box: {trigger_box.name} ({trigger_box.x1},{trigger_box.y1},{trigger_box.x2},{trigger_box.y2})",
            f"trigger_score: {score:.4f}",
            f"screenshot: {screenshot_path or '(not saved)'}",
            "",
        ]
        for item in results:
            lines.extend([f"[{item['name']}]", f"coords: {item['coords']}"])
            lines.append(f"ocr_engine: {item.get('ocr_engine', 'PaddleOCR')}")
            lines.append(f"ocr_lang: {item.get('ocr_lang', '')}")
            if item.get("ocr_filter"):
                lines.append(f"ocr_filter: {item['ocr_filter']}")
            lines.append(f"ocr_preprocess: {item.get('ocr_preprocess', 'default')}")
            if item.get("title_match_mode"):
                lines.append(f"title_match: {item['title_match_mode']} ({item.get('title_match_score', '')})")
            if item.get("raw_text") and item.get("raw_text") != item["text"]:
                lines.append(f"raw_text: {item['raw_text']}")
            if item["error"]:
                lines.append(f"error: {item['error']}")
            if item.get("retry_error"):
                lines.append(f"retry_error: {item['retry_error']}")
            lines.extend(["text:", item["text"], ""])
        path.write_text("\n".join(lines), encoding="utf-8")
