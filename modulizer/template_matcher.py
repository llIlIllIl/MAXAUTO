from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]


class TemplateMatcher:
    def __init__(self, template_path: str) -> None:
        self.template_path = ""
        self.template: Image.Image | None = None
        self.reload(template_path)

    def reload(self, template_path: str) -> None:
        self.template_path = template_path
        self.template = None
        if template_path and Path(template_path).exists():
            self.template = Image.open(template_path).convert("RGB")

    def compare(self, roi: Image.Image) -> float:
        if self.template is None:
            raise RuntimeError("Trigger template image is not configured.")
        search_area = roi.convert("RGB")
        template = self.template.convert("RGB")

        if template.width > search_area.width or template.height > search_area.height:
            return 0.0

        if self._contains_exact_pixels(search_area, template):
            return 1.0
        return self._best_pixel_score(search_area, template)

    @staticmethod
    def _contains_exact_pixels(search_area: Image.Image, template: Image.Image) -> bool:
        if np is not None:
            search_array = np.ascontiguousarray(np.array(search_area))
            template_array = np.ascontiguousarray(np.array(template))
            return TemplateMatcher._numpy_contains_exact_pixels(search_array, template_array)

        max_x = search_area.width - template.width
        max_y = search_area.height - template.height
        for y in range(max_y + 1):
            for x in range(max_x + 1):
                crop = search_area.crop((x, y, x + template.width, y + template.height))
                if ImageChops.difference(crop, template).getbbox() is None:
                    return True
        return False

    @staticmethod
    def _numpy_contains_exact_pixels(search_array: Any, template_array: Any) -> bool:
        search_h, search_w = search_array.shape[:2]
        template_h, template_w = template_array.shape[:2]
        if template_h > search_h or template_w > search_w:
            return False

        first_pixel = template_array[0, 0]
        candidate_map = np.all(
            search_array[: search_h - template_h + 1, : search_w - template_w + 1] == first_pixel,
            axis=-1,
        )
        candidate_y, candidate_x = np.where(candidate_map)
        for y, x in zip(candidate_y, candidate_x):
            if np.array_equal(search_array[y : y + template_h, x : x + template_w], template_array):
                return True
        return False

    @staticmethod
    def _best_pixel_score(search_area: Image.Image, template: Image.Image) -> float:
        max_x = search_area.width - template.width
        max_y = search_area.height - template.height
        if max_x < 0 or max_y < 0:
            return 0.0

        if np is not None:
            search_array = np.ascontiguousarray(np.array(search_area, dtype=np.int16))
            template_array = np.ascontiguousarray(np.array(template, dtype=np.int16))
            template_h, template_w = template_array.shape[:2]
            best_mean_delta = 255.0
            for y in range(max_y + 1):
                for x in range(max_x + 1):
                    candidate = search_array[y : y + template_h, x : x + template_w]
                    mean_delta = float(np.abs(candidate - template_array).mean())
                    if mean_delta < best_mean_delta:
                        best_mean_delta = mean_delta
                        if best_mean_delta == 0.0:
                            return 1.0
            return max(0.0, min(1.0, 1.0 - (best_mean_delta / 255.0)))

        best_score = 0.0
        for y in range(max_y + 1):
            for x in range(max_x + 1):
                crop = search_area.crop((x, y, x + template.width, y + template.height))
                diff = ImageChops.difference(crop, template).convert("L")
                histogram = diff.histogram()
                total = sum(index * count for index, count in enumerate(histogram))
                count = sum(histogram)
                mean_delta = total / max(1, count)
                best_score = max(best_score, 1.0 - (mean_delta / 255.0))
        return max(0.0, min(1.0, best_score))
