from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import APP_DIR


INVALID_FILENAME_CHARS = set('<>:"/\\|?*')


@dataclass(frozen=True)
class RecordDecision:
    should_register: bool
    reason: str
    path: Path
    difficult: str
    title: str
    button: str
    current_score: int | None
    current_fc: int
    stored_score: int | None
    stored_fc: int | None


class ButtonRecordStore:
    def __init__(self, base_dir: Path = APP_DIR) -> None:
        self.base_dir = Path(base_dir)

    def compare(self, values: dict[str, str]) -> RecordDecision:
        button = self._compact(values.get("Button", "")) or "Button"
        difficult = self._compact(values.get("difficult", "")) or "-"
        title = self._compact(values.get("Title", "")) or "-"
        current_score = parse_score(values.get("Score", ""))
        current_fc = fc_from_break(values.get("BREAK", ""))
        path = self.record_path(button)
        records = self.load(path)
        stored = records.get(difficult, {}).get(title)

        if stored is None:
            return RecordDecision(
                should_register=True,
                reason="record_missing",
                path=path,
                difficult=difficult,
                title=title,
                button=button,
                current_score=current_score,
                current_fc=current_fc,
                stored_score=None,
                stored_fc=None,
            )

        stored_score = parse_score(stored.get("Score", ""))
        stored_fc = parse_fc(stored.get("FC", 0))
        score_improved = current_score is not None and (
            stored_score is None or current_score > stored_score
        )
        fc_improved = current_fc == 1 and stored_fc == 0
        should_register = score_improved or fc_improved
        if score_improved:
            reason = "score_improved"
        elif fc_improved:
            reason = "fc_improved"
        else:
            reason = "not_improved"

        return RecordDecision(
            should_register=should_register,
            reason=reason,
            path=path,
            difficult=difficult,
            title=title,
            button=button,
            current_score=current_score,
            current_fc=current_fc,
            stored_score=stored_score,
            stored_fc=stored_fc,
        )

    def update(self, values: dict[str, str]) -> Path:
        button = self._compact(values.get("Button", "")) or "Button"
        difficult = self._compact(values.get("difficult", "")) or "-"
        title = self._compact(values.get("Title", "")) or "-"
        current_score = parse_score(values.get("Score", ""))
        current_fc = fc_from_break(values.get("BREAK", ""))
        path = self.record_path(button)
        records = self.load(path)
        difficult_records = records.setdefault(difficult, {})
        stored = difficult_records.get(title, {})
        stored_score = parse_score(stored.get("Score", ""))
        stored_fc = parse_fc(stored.get("FC", 0))

        best_score = max(
            value for value in (stored_score, current_score, 0) if value is not None
        )
        best_fc = 1 if stored_fc == 1 or current_fc == 1 else 0
        difficult_records[title] = {
            "Score": best_score,
            "FC": best_fc,
        }
        self.save(path, records)
        return path

    def record_path(self, button: str) -> Path:
        safe_button = safe_filename(self._compact(button) or "Button")
        return self.base_dir / f"{safe_button}b.dat"

    @staticmethod
    def load(path: Path) -> dict[str, dict[str, dict[str, int]]]:
        if not path.exists():
            return {}
        raw = path.read_bytes()
        text = ""
        for encoding in ("utf-8-sig", "cp949", "utf-16"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if not text:
            text = raw.decode("utf-8", errors="replace")

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {}

        if not isinstance(data, dict):
            return {}
        records_raw = data.get("records", data)
        if not isinstance(records_raw, dict):
            return {}

        records: dict[str, dict[str, dict[str, int]]] = {}
        for difficult_key, titles_raw in records_raw.items():
            if not isinstance(titles_raw, dict):
                continue
            title_records: dict[str, dict[str, int]] = {}
            for title_key, record_raw in titles_raw.items():
                if not isinstance(record_raw, dict):
                    continue
                score = parse_score(record_raw.get("Score", record_raw.get("score", "")))
                fc = parse_fc(record_raw.get("FC", record_raw.get("fc", 0)))
                title_records[str(title_key)] = {
                    "Score": 0 if score is None else score,
                    "FC": fc,
                }
            records[str(difficult_key)] = title_records
        return records

    @staticmethod
    def save(path: Path, records: dict[str, dict[str, dict[str, int]]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "records": records,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _compact(value: Any) -> str:
        return " ".join(str(value).split()).strip()


def parse_score(value: Any) -> int | None:
    normalized = unicodedata.normalize("NFKC", str(value)).strip()
    normalized = normalized.translate(str.maketrans({"O": "0", "o": "0"}))
    digits = "".join(char for char in normalized if char.isdigit())
    if not digits:
        return None
    return int(digits)


def fc_from_break(value: Any) -> int:
    normalized = unicodedata.normalize("NFKC", str(value)).strip()
    normalized = normalized.translate(str.maketrans({"O": "0", "o": "0"}))
    digits = "".join(char for char in normalized if char.isdigit())
    return 1 if digits and int(digits) == 0 else 0


def parse_fc(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    normalized = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return 1 if normalized in {"1", "true", "yes", "y", "fc"} else 0


def safe_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    chars: list[str] = []
    for char in normalized:
        if char in INVALID_FILENAME_CHARS or ord(char) < 32:
            chars.append("_")
        elif char.isspace():
            chars.append("_")
        else:
            chars.append(char)
    safe = "".join(chars).strip(" ._")
    return safe or "Button"
