from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image


@dataclass
class BoxRegion:
    name: str
    x1: int
    y1: int
    x2: int
    y2: int

    def normalized(self) -> "BoxRegion":
        left, right = sorted((int(self.x1), int(self.x2)))
        top, bottom = sorted((int(self.y1), int(self.y2)))
        return BoxRegion(self.name.strip() or "box", left, top, right, bottom)

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    def crop(self, image: Image.Image) -> Image.Image:
        width, height = image.size
        left = max(0, min(self.x1, width))
        top = max(0, min(self.y1, height))
        right = max(0, min(self.x2, width))
        bottom = max(0, min(self.y2, height))
        if right <= left or bottom <= top:
            raise ValueError(f"Invalid crop area for box '{self.name}'")
        return image.crop((left, top, right, bottom))
