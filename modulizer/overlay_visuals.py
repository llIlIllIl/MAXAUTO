from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont


OverlayKind = Literal["registration", "message"]

BACKGROUND = "#111820"
TEXT_COLOR = "#ffffff"
PROGRESS_TRACK = "#5f6975"

CARD_WIDTH = 520
REGISTRATION_MIN_HEIGHT = 150
MESSAGE_MIN_HEIGHT = 96
MAX_FRAME_WIDTH = 1024
MAX_FRAME_HEIGHT = 256

FRAME_PAD_X = 18
FRAME_PAD_Y = 16
PROGRESS_COLUMN_WIDTH = 60
PROGRESS_SIZE = 46
PROGRESS_RING_INSET = 5
PROGRESS_RING_WIDTH = 4
BUTTON_GAP = 8

BUTTON_STYLES = (
    ("=", "#3b4252"),
    ("Insert", "#1f5f8a"),
    ("Delete", "#8a1f1f"),
)


@dataclass(frozen=True)
class OverlayVisualState:
    kind: OverlayKind
    progress: float = 0.0
    heading: str = ""
    result_difficult: str = ""
    result_button: str = ""
    result_title: str = ""
    result_score: str = ""
    result_score_color: str = TEXT_COLOR
    result_suffix: str = ""
    footer: str = ""
    message: str = ""

    @classmethod
    def registration(
        cls,
        heading: str,
        result_difficult: str,
        result_button: str,
        result_title: str,
        result_score: str,
        result_score_color: str,
        result_suffix: str,
        footer: str,
        progress: float,
    ) -> "OverlayVisualState":
        return cls(
            kind="registration",
            heading=heading,
            result_difficult=result_difficult,
            result_button=result_button,
            result_title=result_title,
            result_score=result_score,
            result_score_color=result_score_color or TEXT_COLOR,
            result_suffix=result_suffix,
            footer=footer,
            progress=progress,
        )

    @classmethod
    def message_card(cls, message: str, progress: float) -> "OverlayVisualState":
        return cls(kind="message", message=message, progress=progress)


def render_overlay_visual(state: OverlayVisualState) -> Image.Image:
    if state.kind == "registration":
        return _render_registration(state)
    if state.kind == "message":
        return _render_message(state)
    raise ValueError(f"Unsupported overlay kind: {state.kind}")


def _render_registration(state: OverlayVisualState) -> Image.Image:
    fonts = _OverlayFonts()
    footer_lines = _clean_lines(state.footer)
    heading_h = _line_height(fonts.heading)
    result_h = _line_height(fonts.result)
    footer_h = _line_height(fonts.footer)
    button_h = _button_height(fonts.button)
    footer_block_h = max(footer_h, len(footer_lines) * footer_h) if footer_lines else 0
    height = min(
        MAX_FRAME_HEIGHT,
        max(
            REGISTRATION_MIN_HEIGHT,
            FRAME_PAD_Y
            + heading_h
            + 2
            + result_h
            + 4
            + footer_block_h
            + 8
            + button_h
            + FRAME_PAD_Y,
        ),
    )
    image = Image.new("RGBA", (CARD_WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_progress(draw, height, state.progress)

    content_left = FRAME_PAD_X + PROGRESS_COLUMN_WIDTH
    content_right = CARD_WIDTH - FRAME_PAD_X
    content_width = content_right - content_left
    y = FRAME_PAD_Y

    _draw_right_text(draw, state.heading, content_right, y, fonts.heading, TEXT_COLOR, content_width)
    y += heading_h + 2

    _draw_result_line(draw, state, content_left, content_right, y, fonts.result)
    y += result_h + 4

    button_y = height - FRAME_PAD_Y - button_h
    footer_bottom = button_y - 8
    if footer_lines and y < footer_bottom:
        max_footer_lines = max(1, (footer_bottom - y) // footer_h)
        visible_lines = footer_lines[:max_footer_lines]
        if len(footer_lines) > max_footer_lines:
            visible_lines[-1] = _ellipsize(visible_lines[-1], fonts.footer, content_width, draw)
        for line in visible_lines:
            _draw_right_text(draw, line, content_right, y, fonts.footer, TEXT_COLOR, content_width)
            y += footer_h

    _draw_buttons(draw, content_right, button_y, fonts.button)
    return image


def _render_message(state: OverlayVisualState) -> Image.Image:
    fonts = _OverlayFonts()
    raw_lines = _clean_lines(state.message) or [""]
    line_h = _line_height(fonts.message)
    message_block_h = len(raw_lines) * line_h
    height = min(MAX_FRAME_HEIGHT, max(MESSAGE_MIN_HEIGHT, FRAME_PAD_Y + message_block_h + FRAME_PAD_Y))
    image = Image.new("RGBA", (CARD_WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_progress(draw, height, state.progress)

    content_left = FRAME_PAD_X + PROGRESS_COLUMN_WIDTH
    content_right = CARD_WIDTH - FRAME_PAD_X
    content_width = content_right - content_left
    max_lines = max(1, (height - (FRAME_PAD_Y * 2)) // line_h)
    lines = raw_lines[:max_lines]
    if len(raw_lines) > max_lines:
        lines[-1] = _ellipsize(lines[-1], fonts.message, content_width, draw)
    block_h = len(lines) * line_h
    y = FRAME_PAD_Y + ((height - (FRAME_PAD_Y * 2) - block_h) // 2)
    for line in lines:
        _draw_right_text(draw, line, content_right, y, fonts.message, TEXT_COLOR, content_width)
        y += line_h
    return image


class _OverlayFonts:
    def __init__(self) -> None:
        self.heading = _load_font(12, bold=False)
        self.footer = _load_font(12, bold=False)
        self.result = _load_font(17, bold=True)
        self.message = _load_font(14, bold=True)
        self.button = _load_font(10, bold=False)


def _load_font(tk_points: int, bold: bool) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    pixel_size = max(1, round(tk_points * 96 / 72))
    candidates = []
    if bold:
        candidates.extend(
            [
                Path(r"C:\Windows\Fonts\malgunbd.ttf"),
                Path(r"C:\Windows\Fonts\malgun.ttf"),
            ]
        )
    else:
        candidates.append(Path(r"C:\Windows\Fonts\malgun.ttf"))
    candidates.extend(
        [
            Path(r"C:\Windows\Fonts\segoeui.ttf"),
            Path(r"C:\Windows\Fonts\arial.ttf"),
        ]
    )
    for path in candidates:
        if not path.exists():
            continue
        try:
            return ImageFont.truetype(str(path), pixel_size)
        except OSError:
            continue
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", pixel_size)
    except OSError:
        return ImageFont.load_default()


def _clean_lines(text: str) -> list[str]:
    lines = []
    for line in str(text).splitlines():
        clean = " ".join(line.split())
        if clean:
            lines.append(clean)
    return lines


def _line_height(font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    if hasattr(font, "getmetrics"):
        ascent, descent = font.getmetrics()
        return int(ascent + descent + 2)
    bbox = font.getbbox("Hg")
    return int((bbox[3] - bbox[1]) + 4)


def _button_height(font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    return _line_height(font) + 8


def _text_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> int:
    if not text:
        return 0
    bbox = draw.textbbox((0, 0), text, font=font)
    return int(bbox[2] - bbox[0])


def _ellipsize(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> str:
    text = str(text)
    if _text_width(draw, text, font) <= max_width:
        return text
    ellipsis = "..."
    if max_width <= _text_width(draw, ellipsis, font):
        return ""
    low = 0
    high = len(text)
    while low < high:
        mid = (low + high + 1) // 2
        candidate = text[:mid].rstrip() + ellipsis
        if _text_width(draw, candidate, font) <= max_width:
            low = mid
        else:
            high = mid - 1
    return text[:low].rstrip() + ellipsis


def _draw_right_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    right: int,
    y: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: str,
    max_width: int,
) -> None:
    fitted = _ellipsize(str(text), font, max_width, draw)
    width = _text_width(draw, fitted, font)
    draw.text((right - width, y), fitted, font=font, fill=fill)


def _draw_result_line(
    draw: ImageDraw.ImageDraw,
    state: OverlayVisualState,
    left: int,
    right: int,
    y: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    max_width = right - left
    score = str(state.result_score)
    suffix = f" {state.result_suffix}" if state.result_suffix else ""
    suffix_width = _text_width(draw, suffix, font)
    score_width = _text_width(draw, score, font)
    fixed_prefix = f"[{state.result_difficult} - {state.result_button}] "
    fixed_tail = " - "
    fixed_width = _text_width(draw, fixed_prefix + fixed_tail, font)
    title_width = max(0, max_width - fixed_width - score_width - suffix_width)
    title = _ellipsize(str(state.result_title), font, title_width, draw)
    prefix = f"{fixed_prefix}{title}{fixed_tail}"
    total_width = _text_width(draw, prefix, font) + score_width + suffix_width
    if total_width > max_width:
        prefix = _ellipsize(prefix, font, max(0, max_width - score_width - suffix_width), draw)
        total_width = _text_width(draw, prefix, font) + score_width + suffix_width
    x = right - total_width
    draw.text((x, y), prefix, font=font, fill=TEXT_COLOR)
    x += _text_width(draw, prefix, font)
    draw.text((x, y), score, font=font, fill=state.result_score_color or TEXT_COLOR)
    x += score_width
    if suffix:
        draw.text((x, y), suffix, font=font, fill=state.result_score_color or TEXT_COLOR)


def _draw_buttons(
    draw: ImageDraw.ImageDraw,
    right: int,
    y: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    x = right
    height = _button_height(font)
    for text, color in reversed(BUTTON_STYLES):
        text_width = _text_width(draw, text, font)
        width = text_width + 28
        x -= width
        draw.rounded_rectangle((x, y, x + width, y + height), radius=0, fill=color)
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_h = text_bbox[3] - text_bbox[1]
        draw.text(
            (x + (width - text_width) // 2, y + (height - text_h) // 2 - 1),
            text,
            font=font,
            fill=TEXT_COLOR,
        )
        x -= BUTTON_GAP


def _draw_progress(draw: ImageDraw.ImageDraw, height: int, progress: float) -> None:
    x = FRAME_PAD_X
    y = (height - PROGRESS_SIZE) // 2
    bbox = (
        x + PROGRESS_RING_INSET,
        y + PROGRESS_RING_INSET,
        x + PROGRESS_SIZE - PROGRESS_RING_INSET,
        y + PROGRESS_SIZE - PROGRESS_RING_INSET,
    )
    draw.ellipse(bbox, outline=PROGRESS_TRACK, width=PROGRESS_RING_WIDTH)
    clamped = max(0.0, min(1.0, float(progress)))
    if clamped <= 0.0:
        return
    draw.arc(
        bbox,
        start=-90,
        end=-90 + (359.9 * clamped),
        fill=TEXT_COLOR,
        width=PROGRESS_RING_WIDTH,
    )
