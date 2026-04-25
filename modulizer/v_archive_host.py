from __future__ import annotations

import json
import platform
import queue
import socket
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .constants import APP_DIR
from .v_archive_api import RECORD_API_BASE_URL, decode_json_response


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
VALID_BUTTONS = ("4", "5", "6", "8")


def default_html_path() -> Path:
    bundle_dir = Path(getattr(sys, "_MEIPASS", APP_DIR))
    candidates = (
        APP_DIR / "v-archive.html",
        bundle_dir / "v-archive.html",
        Path(__file__).resolve().parent.parent / "v-archive.html",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return APP_DIR / "v-archive.html"


def lan_ip_address() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
        if address and not address.startswith("127."):
            return address
    except OSError:
        pass

    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = item[4][0]
            if address and not address.startswith(("127.", "169.254.")):
                return address
    except OSError:
        pass
    return "127.0.0.1"


def firewall_rule_command(port: int) -> str:
    return (
        "New-NetFirewallRule "
        "-DisplayName 'MAXOCR V-ARCHIVE Host' "
        "-Direction Inbound "
        "-Action Allow "
        "-Protocol TCP "
        f"-LocalPort {int(port)} "
        "-Profile Any"
    )


def can_request_windows_firewall_rule() -> bool:
    return platform.system().lower() == "windows"


def request_windows_firewall_rule(port: int) -> bool:
    if not can_request_windows_firewall_rule():
        return False
    try:
        import ctypes

        command = firewall_rule_command(port)
        args = f'-NoProfile -ExecutionPolicy Bypass -Command "{command}"'
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "powershell.exe",
            args,
            None,
            1,
        )
        return int(result) > 32
    except Exception:
        return False


class VArchiveHostServer:
    def __init__(
        self,
        html_path: Path | None = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.html_path = Path(html_path) if html_path is not None else default_html_path()
        self.host = host
        self.port = int(port)
        self.timeout_seconds = float(timeout_seconds)
        self.username = ""
        self.button = ""
        self._server: _ArchiveThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._subscribers: set[queue.Queue[str | None]] = set()
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._thread is not None and self._thread.is_alive()

    @property
    def url(self) -> str:
        if not self.is_running:
            return ""
        display_host = lan_ip_address() if self.host in ("", "0.0.0.0") else self.host
        query = urllib.parse.urlencode({"u": self.username, "btn": self.button})
        return f"http://{display_host}:{self.port}/v-archive.html?{query}"

    @property
    def local_url(self) -> str:
        if not self.is_running:
            return ""
        query = urllib.parse.urlencode({"u": self.username, "btn": self.button})
        return f"http://127.0.0.1:{self.port}/v-archive.html?{query}"

    def can_reach_lan_url(self, timeout_seconds: float = 1.0) -> bool:
        if not self.is_running:
            return False
        host = lan_ip_address() if self.host in ("", "0.0.0.0") else self.host
        if host.startswith("127."):
            return False
        try:
            with socket.create_connection((host, self.port), timeout=timeout_seconds):
                return True
        except OSError:
            return False

    def start(self, username: str, button: str, port: int | None = None) -> None:
        clean_username = str(username).strip()
        clean_button = str(button).strip()
        clean_port = int(self.port if port is None else port)
        if not clean_username:
            raise ValueError("V-ARCHIVE 유저네임을 입력하세요.")
        if clean_button not in VALID_BUTTONS:
            raise ValueError("btn 값은 4, 5, 6, 8 중 하나여야 합니다.")
        if clean_port < 0 or clean_port > 65535:
            raise ValueError("포트 값은 1-65535 사이여야 합니다.")
        if not self.html_path.exists():
            raise FileNotFoundError(f"v-archive.html 파일을 찾을 수 없습니다: {self.html_path}")

        self.stop()
        self.username = clean_username
        self.button = clean_button
        self.port = clean_port

        server = _ArchiveThreadingHTTPServer((self.host, self.port), _VArchiveRequestHandler)
        server.app = self
        self.port = int(server.server_address[1])
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        self._close_subscribers()
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def notify_refresh(self) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put("refresh")

    def subscribe(self) -> queue.Queue[str | None]:
        subscriber: queue.Queue[str | None] = queue.Queue()
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[str | None]) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def _close_subscribers(self) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
            self._subscribers.clear()
        for subscriber in subscribers:
            subscriber.put(None)

    def fetch_dj_class(self, username: str, button: str) -> tuple[int, dict[str, Any]]:
        clean_username = str(username).strip()
        clean_button = str(button).strip()
        if not clean_username:
            return int(HTTPStatus.BAD_REQUEST), {"success": False, "message": "u 파라미터가 필요합니다."}
        if clean_button not in VALID_BUTTONS:
            return int(HTTPStatus.BAD_REQUEST), {"success": False, "message": "btn 파라미터는 4, 5, 6, 8 중 하나여야 합니다."}

        encoded_username = urllib.parse.quote(clean_username, safe="")
        url = f"{RECORD_API_BASE_URL}/{encoded_username}/djClass/{clean_button}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return int(response.status), decode_json_response(response.read())
        except urllib.error.HTTPError as exc:
            return int(exc.code), decode_json_response(exc.read())
        except urllib.error.URLError as exc:
            return int(HTTPStatus.BAD_GATEWAY), {"success": False, "message": f"V-ARCHIVE 요청 실패: {exc.reason}"}


class _ArchiveThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    app: VArchiveHostServer


class _VArchiveRequestHandler(BaseHTTPRequestHandler):
    server_version = "MAXOCRVArchiveHost/1.0"

    @property
    def app(self) -> VArchiveHostServer:
        return self.server.app  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("", "/", "/v-archive.html"):
            self._serve_html()
            return
        if parsed.path == "/api/dj-class":
            self._serve_dj_class(parsed.query)
            return
        if parsed.path == "/events":
            self._serve_events()
            return
        if parsed.path == "/health":
            self._send_json(HTTPStatus.OK, {"success": True})
            return
        if parsed.path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _serve_html(self) -> None:
        try:
            data = self.app.html_path.read_bytes()
        except OSError as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"success": False, "message": f"v-archive.html 읽기 실패: {exc}"},
            )
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_dj_class(self, query: str) -> None:
        params = urllib.parse.parse_qs(query, keep_blank_values=True)
        username = params.get("u", [""])[0]
        button = params.get("btn", [""])[0]
        status, payload = self.app.fetch_dj_class(username, button)
        self._send_json(status, payload)

    def _serve_events(self) -> None:
        subscriber = self.app.subscribe()
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self._write_event("ready", {})
            while True:
                event = subscriber.get()
                if event is None:
                    break
                if event == "refresh":
                    self._write_event("refresh", {})
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.app.unsubscribe(subscriber)

    def _write_event(self, event: str, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False)
        self.wfile.write(f"event: {event}\ndata: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _send_json(self, status: int | HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: Any) -> None:
        return
