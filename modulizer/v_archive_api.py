from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from .constants import APP_DIR
from .record_store import fc_from_break, parse_score


API_BASE_URL = "https://v-archive.net/client/open"
ACCOUNT_PATH = APP_DIR / "account.txt"
PATTERN_MAP = {
    "NM": "NORMAL",
    "NORMAL": "NORMAL",
    "HD": "HARD",
    "HARD": "HARD",
    "MX": "MAXIMUM",
    "MAXIMUM": "MAXIMUM",
    "SC": "SC",
}


@dataclass(frozen=True)
class AccountCredentials:
    user_no: str
    token: str


@dataclass(frozen=True)
class ScoreApiResult:
    success: bool
    update: bool | None
    message: str
    status_code: int | None
    error_code: int | None
    payload: dict[str, Any]
    request_payload: dict[str, Any]


class VArchiveScoreClient:
    def __init__(self, account_path: Path = ACCOUNT_PATH, timeout_seconds: float = 10.0) -> None:
        self.account_path = Path(account_path)
        self.timeout_seconds = float(timeout_seconds)

    def submit(self, values: dict[str, str]) -> ScoreApiResult:
        credentials = self.load_credentials()
        payload = build_score_payload(values)
        result = self._post_score(credentials, payload)
        if result.status_code == 404 and result.error_code == 202:
            retry_payload = dict(payload)
            retry_payload["composer"] = compact_value(values.get("ARTIST", ""))
            result = self._post_score(credentials, retry_payload)
        return result

    def load_credentials(self) -> AccountCredentials:
        if not self.account_path.exists():
            raise RuntimeError(f"account.txt 파일을 찾을 수 없습니다: {self.account_path}")
        text = self.account_path.read_text(encoding="utf-8-sig").strip()
        parts = text.split()
        if len(parts) < 2:
            raise RuntimeError("account.txt 형식이 올바르지 않습니다. userNo token 형식이어야 합니다.")
        return AccountCredentials(user_no=parts[0], token=parts[1])

    def _post_score(self, credentials: AccountCredentials, payload: dict[str, Any]) -> ScoreApiResult:
        url = f"{API_BASE_URL}/{credentials.user_no}/score"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": credentials.token,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                status_code = int(response.status)
                response_payload = decode_json_response(response.read())
        except urllib.error.HTTPError as exc:
            status_code = int(exc.code)
            response_payload = decode_json_response(exc.read())
            return result_from_response(status_code, response_payload, payload)
        except urllib.error.URLError as exc:
            raise RuntimeError(f"API 요청 실패: {exc.reason}") from exc

        return result_from_response(status_code, response_payload, payload)


def build_score_payload(values: dict[str, str]) -> dict[str, Any]:
    title = compact_value(values.get("Title", ""))
    if not title:
        raise ValueError("Title 값이 비어 있습니다.")

    score = parse_score(values.get("Score", ""))
    if score is None:
        raise ValueError("Score 값을 숫자로 해석할 수 없습니다.")

    return {
        "name": title,
        "button": parse_button(values.get("Button", "")),
        "pattern": parse_pattern(values.get("difficult", "")),
        "score": score_to_accuracy(score),
        "maxCombo": fc_from_break(values.get("BREAK", "")),
    }


def parse_button(value: Any) -> int:
    normalized = compact_value(value).upper()
    if normalized in {"4", "5", "6", "8"}:
        return int(normalized)
    match = re.fullmatch(r"([4568])\s*B", normalized)
    if match is not None:
        return int(match.group(1))
    raise ValueError(f"Button 값을 버튼 개수로 해석할 수 없습니다: {value}")


def parse_pattern(value: Any) -> str:
    normalized = compact_value(value).upper()
    normalized = normalized.replace(" ", "")
    pattern = PATTERN_MAP.get(normalized)
    if pattern is None:
        raise ValueError(f"difficult 값을 패턴으로 해석할 수 없습니다: {value}")
    return pattern


def score_to_accuracy(score: int) -> float:
    accuracy = (Decimal(int(score)) / Decimal("10000")).quantize(
        Decimal("0.0001"),
        rounding=ROUND_HALF_UP,
    )
    return float(accuracy)


def decode_json_response(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    text = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"message": text}
    return data if isinstance(data, dict) else {"data": data}


def result_from_response(
    status_code: int,
    response_payload: dict[str, Any],
    request_payload: dict[str, Any],
) -> ScoreApiResult:
    success = bool(response_payload.get("success")) and 200 <= status_code < 300
    update_raw = response_payload.get("update")
    update = bool(update_raw) if isinstance(update_raw, bool) else None
    error_code_raw = response_payload.get("errorCode")
    error_code = int(error_code_raw) if isinstance(error_code_raw, int) else None
    return ScoreApiResult(
        success=success,
        update=update,
        message=response_message(status_code, error_code, success, update, response_payload),
        status_code=status_code,
        error_code=error_code,
        payload=response_payload,
        request_payload=request_payload,
    )


def response_message(
    status_code: int,
    error_code: int | None,
    success: bool,
    update: bool | None,
    response_payload: dict[str, Any],
) -> str:
    if success and update is False:
        return "서버에 더 좋은 기록이 있어 갱신되지 않았습니다."
    if success:
        return ""
    if status_code == 404 and error_code == 211:
        return "서버에서 실제로 존재하지 않는 패턴으로 인식했습니다."
    if status_code == 500:
        return "API 서버 에러입니다."
    if status_code == 404 and error_code == 201:
        return "서버에서 곡을 찾지 못했습니다."
    if status_code == 404 and error_code == 202:
        return "서버에서 곡을 특정하지 못했습니다."
    if status_code == 400 and error_code == 900:
        return "API 요청 값이 올바르지 않습니다."
    fallback = response_payload.get("message")
    return str(fallback) if fallback else f"API 요청 실패: HTTP {status_code}"


def compact_value(value: Any) -> str:
    return " ".join(str(value).split()).strip()
