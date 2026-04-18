from __future__ import annotations

import difflib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .constants import DEFAULT_TITLE_DAT_PATH


@dataclass(frozen=True)
class TitleResolution:
    title: str
    mode: str
    score: float


class TitleCatalog:
    def __init__(self, path: Path = DEFAULT_TITLE_DAT_PATH) -> None:
        self.path = path
        self._titles: list[str] | None = None

    def resolve(self, text: str) -> TitleResolution | None:
        source = self._compact(text)
        titles = self.titles
        if not source or not titles:
            return None

        exact_titles = {self._compact(title): title for title in titles}
        exact = exact_titles.get(source)
        if exact is not None:
            return TitleResolution(title=exact, mode="exact", score=1.0)

        source_key = self._similarity_key(source)
        best_title = titles[0]
        best_score = -1.0
        for title in titles:
            score = difflib.SequenceMatcher(None, source_key, self._similarity_key(title)).ratio()
            if score > best_score:
                best_title = title
                best_score = score
        return TitleResolution(title=best_title, mode="similar", score=max(0.0, best_score))

    @property
    def titles(self) -> list[str]:
        if self._titles is None:
            self._titles = self._load_titles()
        return self._titles

    def _load_titles(self) -> list[str]:
        if not self.path.exists():
            return []
        raw = self.path.read_bytes()
        for encoding in ("utf-8-sig", "cp949", "utf-16"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
        return [line.strip() for line in text.splitlines() if line.strip()]

    @staticmethod
    def _compact(text: str) -> str:
        return " ".join(str(text).split()).strip()

    @staticmethod
    def _similarity_key(text: str) -> str:
        return unicodedata.normalize("NFKC", TitleCatalog._compact(text)).casefold()
