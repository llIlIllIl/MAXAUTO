from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .constants import (
    APP_DIR,
    CLI_ARG_GAME_OVERLAY_HELPER,
    CLI_ARG_GAME_OVERLAY_HELPER_COMMAND,
    CLI_ARG_GAME_OVERLAY_HELPER_PARENT_PID,
    CLI_ARG_GAME_OVERLAY_HELPER_RESPONSE,
    CLI_ARG_GAME_OVERLAY_HELPER_SETTINGS,
)
from .config import (
    DEFAULT_GAME_OVERLAY_ATTACH_STRATEGY,
    DEFAULT_GAME_OVERLAY_STEAM_APP_ID,
    DEFAULT_GAME_OVERLAY_TARGET_PROCESS,
)
from .overlay_visuals import MAX_FRAME_HEIGHT, MAX_FRAME_WIDTH, OverlayVisualState, render_overlay_visual


OVERLAY_HIDDEN_OFFSET = 24
HELPER_POLL_INTERVAL_SECONDS = 0.2
HELPER_RESPONSE_TIMEOUT_SECONDS = 20.0
HELPER_STOP_TIMEOUT_SECONDS = 5.0
WAIT_TIMEOUT = 0x00000102


@dataclass(frozen=True)
class GameOverlaySettings:
    target_process: str = DEFAULT_GAME_OVERLAY_TARGET_PROCESS
    steam_app_id: int = DEFAULT_GAME_OVERLAY_STEAM_APP_ID
    exe_path: str = ""
    attach_strategy: str = DEFAULT_GAME_OVERLAY_ATTACH_STRATEGY


@dataclass(frozen=True)
class GameOverlayResult:
    success: bool
    message: str
    launched_process: bool = False
    fatal: bool = False


class GameOverlayBackend:
    card_width = 64
    progress_width = 34
    bitmap_sender_names = ("send_overlay_frame", "send_bitmap_frame", "send_bitmap")
    bitmap_clear_names = ("clear_overlay_frame", "clear_bitmap_frame", "clear_bitmap")

    def __init__(self, settings: GameOverlaySettings) -> None:
        self.settings = settings
        self.injector: Any | None = None
        self.started = False
        self.launched_process = False
        self.bitmap_seq = 0

    @staticmethod
    def validate_import() -> GameOverlayResult:
        GameOverlayBackend.ensure_vendor_sdk_path()
        try:
            import game_overlay_sdk.injector  # noqa: F401
        except Exception as exc:
            return GameOverlayResult(
                success=False,
                message=f"game-overlay-sdk 필수 의존성을 불러올 수 없습니다: {exc}",
            )
        return GameOverlayResult(success=True, message="game-overlay-sdk 의존성 확인 완료")

    @staticmethod
    def is_elevated() -> bool:
        if os.name != "nt":
            return True
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def start(self) -> GameOverlayResult:
        if self.started:
            return GameOverlayResult(
                success=True,
                message="game-overlay-sdk 오버레이가 이미 시작되어 있습니다.",
                launched_process=self.launched_process,
            )

        try:
            self.ensure_vendor_sdk_path()
            import game_overlay_sdk.injector as injector
        except Exception as exc:
            return GameOverlayResult(
                success=False,
                message=f"game-overlay-sdk 필수 의존성을 불러올 수 없습니다: {exc}",
            )

        if not self.is_elevated():
            return GameOverlayResult(
                success=False,
                message=(
                    "game-overlay-sdk는 관리자 권한으로 실행해야 합니다. "
                    "Windows Error 5(Access denied)를 피하려면 MAXOCR을 관리자 권한으로 다시 실행하세요."
                ),
            )

        self.injector = injector
        self._enable_logger()

        try:
            path = self.resolve_game_exe_path()
            if path is not None:
                appid_result = self.ensure_steam_appid_file(path.parent)
                if not appid_result.success:
                    return appid_result

                self.injector.run_process(str(path), "", int(self.settings.steam_app_id))
                self.started = True
                self.launched_process = True
                self._clear_startup_overlay()
                return GameOverlayResult(
                    success=True,
                    message=f"{appid_result.message}\ngame-overlay-sdk run_process 시작: {path.name}",
                    launched_process=True,
                )

            target_process = str(self.settings.target_process or DEFAULT_GAME_OVERLAY_TARGET_PROCESS).strip()
            self.injector.start_monitor(target_process)
            self.started = True
            self.launched_process = False
            return GameOverlayResult(
                success=True,
                message=(
                    f"game-overlay-sdk start_monitor 시작: {target_process} "
                    "게임 EXE 경로가 비어 있어 steam_appid.txt 자동 생성은 건너뜁니다."
                ),
            )
        except Exception as exc:
            self.started = False
            return GameOverlayResult(
                success=False,
                message=self.format_start_error(exc),
            )

    def resolve_game_exe_path(self) -> Path | None:
        exe_path = str(self.settings.exe_path or "").strip()
        if exe_path:
            path = Path(exe_path).expanduser()
            if path.exists():
                return path
            raise FileNotFoundError(f"게임 실행 파일을 찾을 수 없습니다: {path}")
        return self.find_steam_game_exe()

    def stop(self) -> GameOverlayResult:
        if self.injector is None:
            self.started = False
            return GameOverlayResult(success=True, message="game-overlay-sdk 오버레이가 시작되어 있지 않습니다.")
        try:
            self.clear()
            self.injector.release_resources()
            return GameOverlayResult(success=True, message="game-overlay-sdk 오버레이 리소스 해제 완료")
        except Exception as exc:
            return GameOverlayResult(success=False, message=f"game-overlay-sdk 리소스 해제 실패: {exc}")
        finally:
            self.started = False
            self.launched_process = False
            self.injector = None

    def show_registration(self, event: dict[str, Any]) -> GameOverlayResult:
        return self.send_text(self.format_registration_message(event))

    def show_registration_card(
        self,
        heading: str,
        result_difficult: str,
        result_button: str,
        result_title: str,
        result_score: str,
        result_suffix: str,
        footer: str,
        progress: float,
        result_score_color: str = "white",
        reveal: float = 1.0,
    ) -> GameOverlayResult:
        state = OverlayVisualState.registration(
            heading=heading,
            result_difficult=result_difficult,
            result_button=result_button,
            result_title=result_title,
            result_score=result_score,
            result_score_color=result_score_color,
            result_suffix=result_suffix,
            footer=footer,
            progress=progress,
        )
        return self.send_overlay_frame(state, reveal=reveal)

    def show_message(self, message: str) -> GameOverlayResult:
        return self.show_message_card(str(message), 0.0)

    def show_message_card(self, message: str, progress: float, reveal: float = 1.0) -> GameOverlayResult:
        return self.send_overlay_frame(OverlayVisualState.message_card(str(message), progress), reveal=reveal)

    def clear(self) -> GameOverlayResult:
        if self.injector is None or not self.started:
            return GameOverlayResult(success=True, message="")
        try:
            if not self._send_bitmap_clear():
                self.injector.send_message("")
            return GameOverlayResult(success=True, message="game-overlay-sdk 오버레이 비움")
        except Exception as exc:
            return GameOverlayResult(success=False, message=f"game-overlay-sdk 오버레이 비우기 실패: {exc}")

    def send_overlay_frame(self, state: OverlayVisualState, reveal: float = 1.0) -> GameOverlayResult:
        if self.injector is None or not self.started:
            return GameOverlayResult(success=False, message="game-overlay-sdk overlay is not started.")
        try:
            image = render_overlay_visual(state)
            image = self.compose_animation_frame(image, reveal)
        except Exception as exc:
            return GameOverlayResult(success=False, message=f"game-overlay-sdk bitmap overlay render failed: {exc}")
        return self.send_bitmap_image(image)

    @staticmethod
    def compose_animation_frame(image: Any, reveal: float) -> Any:
        clamped = max(0.0, min(1.0, float(reveal)))
        width, height = image.size
        if width > MAX_FRAME_WIDTH or height > MAX_FRAME_HEIGHT:
            return image
        if clamped >= 1.0 and width == MAX_FRAME_WIDTH:
            return image
        if clamped >= 1.0 and width < MAX_FRAME_WIDTH:
            return image

        frame = Image.new("RGBA", (MAX_FRAME_WIDTH, height), (0, 0, 0, 0))
        visible_x = MAX_FRAME_WIDTH - width
        hidden_x = MAX_FRAME_WIDTH + OVERLAY_HIDDEN_OFFSET
        x = round(hidden_x + ((visible_x - hidden_x) * clamped))
        if x >= MAX_FRAME_WIDTH:
            return frame

        card = image.convert("RGBA")
        if x + width > MAX_FRAME_WIDTH:
            visible_width = max(0, MAX_FRAME_WIDTH - x)
            if visible_width <= 0:
                return frame
            card = card.crop((0, 0, visible_width, height))
        frame.alpha_composite(card, (max(0, x), 0))
        return frame

    def send_bitmap_image(self, image: Any) -> GameOverlayResult:
        if self.injector is None or not self.started:
            return GameOverlayResult(success=False, message="game-overlay-sdk overlay is not started.")
        width, height = image.size
        if width > MAX_FRAME_WIDTH or height > MAX_FRAME_HEIGHT:
            return GameOverlayResult(
                success=False,
                message=f"game-overlay-sdk bitmap frame too large: {width}x{height} > {MAX_FRAME_WIDTH}x{MAX_FRAME_HEIGHT}",
            )
        sender = self._bitmap_sender()
        if sender is None:
            return GameOverlayResult(
                success=False,
                message="game-overlay-sdk bitmap API is unavailable. Extended SDK support is required.",
            )
        try:
            rgba_image = image.convert("RGBA")
            self._send_bitmap_payload(
                sender,
                visible=True,
                width=int(rgba_image.width),
                height=int(rgba_image.height),
                rgba=rgba_image.tobytes("raw", "RGBA"),
            )
            return GameOverlayResult(success=True, message="game-overlay-sdk bitmap overlay sent")
        except Exception as exc:
            return GameOverlayResult(success=False, message=f"game-overlay-sdk bitmap overlay send failed: {exc}")

    def send_text(self, message: str) -> GameOverlayResult:
        if self.injector is None or not self.started:
            return GameOverlayResult(success=False, message="game-overlay-sdk 오버레이가 시작되지 않았습니다.")
        try:
            self.injector.send_message(str(message))
            return GameOverlayResult(success=True, message="game-overlay-sdk 오버레이 메시지 전송 완료")
        except Exception as exc:
            return GameOverlayResult(success=False, message=f"game-overlay-sdk 오버레이 메시지 전송 실패: {exc}")

    def _bitmap_sender(self) -> Any | None:
        if self.injector is None:
            return None
        for name in self.bitmap_sender_names:
            sender = getattr(self.injector, name, None)
            if callable(sender):
                return sender
        return None

    def _send_bitmap_clear(self) -> bool:
        if self.injector is None:
            return False
        for name in self.bitmap_clear_names:
            clear = getattr(self.injector, name, None)
            if callable(clear):
                try:
                    clear()
                    return True
                except TypeError:
                    pass
        sender = self._bitmap_sender()
        if sender is None:
            return False
        self._send_bitmap_payload(sender, visible=False, width=1, height=1, rgba=b"\x00\x00\x00\x00")
        return True

    def _send_bitmap_payload(self, sender: Any, visible: bool, width: int, height: int, rgba: bytes) -> None:
        stride = int(width) * 4
        self.bitmap_seq = (self.bitmap_seq + 1) & 0xFFFFFFFF
        frame = {
            "visible": bool(visible),
            "width": int(width),
            "height": int(height),
            "stride": stride,
            "seq": self.bitmap_seq,
            "rgba": rgba,
        }
        frame_with_alias = {**frame, "pixels": rgba}
        attempts = (
            lambda: sender(frame_with_alias),
            lambda: sender(frame),
            lambda: sender(**frame),
            lambda: sender(**frame_with_alias),
            lambda: sender(bool(visible), int(width), int(height), stride, self.bitmap_seq, rgba),
            lambda: sender(int(width), int(height), stride, rgba),
            lambda: sender(int(width), int(height), rgba),
        )
        last_error: Exception | None = None
        for attempt in attempts:
            try:
                attempt()
                return
            except TypeError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error

    def ensure_steam_appid_file(self, game_dir: Path) -> GameOverlayResult:
        app_id = int(self.settings.steam_app_id or 0)
        if app_id <= 0:
            return GameOverlayResult(success=True, message="Steam App ID가 없어 steam_appid.txt 생성을 건너뜁니다.")

        appid_file = game_dir / "steam_appid.txt"
        expected = str(app_id)
        try:
            if appid_file.exists() and appid_file.read_text(encoding="ascii", errors="ignore").strip() == expected:
                return GameOverlayResult(success=True, message=f"steam_appid.txt 확인: {expected}")
            appid_file.write_text(expected + "\n", encoding="ascii")
            return GameOverlayResult(success=True, message=f"steam_appid.txt 생성/갱신: {appid_file.name}={expected}")
        except OSError as exc:
            return GameOverlayResult(
                success=False,
                message=(
                    f"steam_appid.txt 생성 실패: {appid_file} ({exc}). "
                    "게임 폴더 쓰기 권한 또는 관리자 권한을 확인하세요."
                ),
            )

    def find_steam_game_exe(self) -> Path | None:
        app_id = int(self.settings.steam_app_id or 0)
        if app_id <= 0:
            return None

        for library_dir in self.steam_library_dirs():
            manifest = library_dir / "steamapps" / f"appmanifest_{app_id}.acf"
            if not manifest.exists():
                continue
            install_dir = self.parse_steam_install_dir(manifest)
            if not install_dir:
                continue
            game_dir = library_dir / "steamapps" / "common" / install_dir
            target_process = str(self.settings.target_process or DEFAULT_GAME_OVERLAY_TARGET_PROCESS).strip()
            exe = game_dir / target_process
            if exe.exists():
                return exe
        return None

    @classmethod
    def steam_library_dirs(cls) -> list[Path]:
        roots = cls.steam_roots()
        libraries: list[Path] = []
        for root in roots:
            if root.exists() and root not in libraries:
                libraries.append(root)
            libraryfolders = root / "steamapps" / "libraryfolders.vdf"
            if not libraryfolders.exists():
                continue
            try:
                text = libraryfolders.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for match in re.finditer(r'"path"\s+"([^"]+)"', text):
                path = Path(match.group(1).replace("\\\\", "\\"))
                if path.exists() and path not in libraries:
                    libraries.append(path)
        return libraries

    @staticmethod
    def steam_roots() -> list[Path]:
        roots: list[Path] = []
        if os.name == "nt":
            try:
                import winreg

                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                    steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
                roots.append(Path(str(steam_path)))
            except OSError:
                pass
        for value in (
            os.environ.get("STEAM_PATH"),
            os.environ.get("STEAM_DIR"),
            r"C:\Program Files (x86)\Steam",
            r"C:\Program Files\Steam",
        ):
            if value:
                path = Path(value)
                if path not in roots:
                    roots.append(path)
        return roots

    @staticmethod
    def parse_steam_install_dir(manifest: Path) -> str:
        try:
            text = manifest.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""
        match = re.search(r'"installdir"\s+"([^"]+)"', text)
        return match.group(1).strip() if match else ""

    def format_start_error(self, exc: Exception) -> str:
        text = str(exc)
        hints: list[str] = []
        if "Error 5" in text or "error 5" in text or "Access" in text or "access" in text:
            hints.append("Windows Error 5는 접근 거부입니다. MAXOCR을 관리자 권한으로 실행하세요.")
            hints.append("게임이 관리자 권한으로 실행 중이면 MAXOCR도 같은 권한 수준이어야 합니다.")
        if self.settings.exe_path:
            hints.append("Steam 게임은 게임 폴더의 steam_appid.txt가 960170인지 확인하세요.")
        else:
            hints.append("Steam 자동 탐색이 실패하면 게임 EXE 경로를 직접 지정하세요.")
        suffix = " ".join(hints)
        return f"game-overlay-sdk 오버레이 시작 실패: {text}" + (f" {suffix}" if suffix else "")

    def _enable_logger(self) -> None:
        if self.injector is None:
            return
        try:
            self.injector.enable_monitor_logger()
        except Exception:
            pass

    def _clear_startup_overlay(self) -> None:
        try:
            self.clear()
        except Exception:
            pass

    @staticmethod
    def ensure_vendor_sdk_path() -> None:
        vendor_python = Path(__file__).resolve().parent.parent / "vendor" / "game_overlay_sdk" / "python"
        if vendor_python.exists():
            vendor_text = str(vendor_python)
            if vendor_text not in sys.path:
                sys.path.insert(0, vendor_text)

    @staticmethod
    def format_registration_message(event: dict[str, Any]) -> str:
        result_map = {
            str(item.get("name", "")): str(item.get("text", "")).strip()
            for item in event.get("results", [])
            if isinstance(item, dict)
        }
        button = result_map.get("Button", str(event.get("trigger_box_name", "Button"))).strip() or "Button"
        difficult = result_map.get("difficult", "").strip() or "-"
        title = result_map.get("Title", "").strip() or "-"
        score = result_map.get("Score", "").strip() or "-"
        break_value = result_map.get("BREAK", "").strip()
        score_line = f"{score} / BREAK {break_value}" if break_value else score
        return GameOverlayBackend.format_registration_card(
            heading="MAXOCR 등록 대기",
            result_difficult=difficult,
            result_button=button,
            result_title=title,
            result_score=score,
            result_suffix=f"/ BREAK {break_value}" if break_value else "",
            footer="Enter 등록 / Delete 취소 / Insert 재인식 / = 수동입력",
            progress=0.0,
        )

    @classmethod
    def format_registration_card(
        cls,
        heading: str,
        result_difficult: str,
        result_button: str,
        result_title: str,
        result_score: str,
        result_suffix: str,
        footer: str,
        progress: float,
    ) -> str:
        score_line = f"{result_score} {result_suffix}".strip()
        lines = [
            heading,
            f"[{result_difficult} - {result_button}] {result_title}",
            score_line,
            *[line for line in str(footer).splitlines() if line.strip()],
            cls.progress_line(progress),
        ]
        return cls.format_card(lines)

    @classmethod
    def format_message_card(cls, message: str, progress: float) -> str:
        lines = [
            *[line for line in str(message).splitlines() if line.strip()],
            cls.progress_line(progress),
        ]
        return cls.format_card(lines)

    @classmethod
    def format_card(cls, lines: list[str]) -> str:
        width = cls.card_width
        border = "+" + ("-" * (width + 2)) + "+"
        body = [border]
        for line in lines:
            for wrapped in cls.wrap_line(str(line), width):
                body.append(f"| {wrapped.ljust(width)} |")
        body.append(border)
        return "\n".join(body)

    @classmethod
    def wrap_line(cls, text: str, width: int) -> list[str]:
        text = " ".join(str(text).split())
        if not text:
            return [""]
        chunks: list[str] = []
        while text:
            chunks.append(text[:width])
            text = text[width:]
        return chunks

    @classmethod
    def progress_line(cls, progress: float) -> str:
        clamped = max(0.0, min(1.0, float(progress)))
        filled = round(cls.progress_width * clamped)
        bar = "#" * filled + "-" * (cls.progress_width - filled)
        percent = max(0, round(clamped * 100))
        return f"[{bar}] {percent:3d}%"


class GameOverlayElevatedProxyBackend(GameOverlayBackend):
    def __init__(self, settings: GameOverlaySettings) -> None:
        super().__init__(settings)
        self.helper_dir: Path | None = None
        self.helper_settings_path: Path | None = None
        self.helper_response_path: Path | None = None
        self.helper_command_path: Path | None = None
        self.helper_pid = 0

    def start(self) -> GameOverlayResult:
        if self.started:
            return GameOverlayResult(
                success=True,
                message="game-overlay-sdk 관리자 helper가 이미 시작되어 있습니다.",
                launched_process=self.launched_process,
            )

        try:
            self.ensure_vendor_sdk_path()
            import game_overlay_sdk.injector as injector
        except Exception as exc:
            return GameOverlayResult(
                success=False,
                message=f"game-overlay-sdk 필수 구성요소를 불러올 수 없습니다: {exc}",
            )

        session_dir = Path(tempfile.mkdtemp(prefix="maxocr_game_overlay_"))
        settings_path = session_dir / "settings.json"
        response_path = session_dir / "response.json"
        command_path = session_dir / "command.json"
        self.helper_dir = session_dir
        self.helper_settings_path = settings_path
        self.helper_response_path = response_path
        self.helper_command_path = command_path
        self.helper_pid = 0

        try:
            write_json_file(settings_path, asdict(self.settings))
            executable, parameters = self._helper_launch_command(
                settings_path=settings_path,
                response_path=response_path,
                command_path=command_path,
                parent_pid=os.getpid(),
            )
            launch_result = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                executable,
                parameters,
                str(APP_DIR),
                0,
            )
            if int(launch_result) <= 32:
                self._cleanup_helper_session()
                return GameOverlayResult(
                    success=False,
                    message=(
                        "관리자 권한 요청이 취소되었거나 실패했습니다. "
                        f"ShellExecuteW={int(launch_result)}"
                    ),
                    fatal=True,
                )

            response = self._wait_for_helper_response(response_path)
            if response is None:
                self._signal_helper_stop()
                self._cleanup_helper_session()
                return GameOverlayResult(
                    success=False,
                    message="관리자 권한 helper가 시간 안에 응답하지 않았습니다.",
                    fatal=True,
                )

            self.helper_pid = int(response.get("helper_pid", 0) or 0)
            result = GameOverlayResult(
                success=bool(response.get("success", False)),
                message=str(response.get("message", "")),
                launched_process=bool(response.get("launched_process", False)),
                fatal=bool(response.get("fatal", False)),
            )
            if not result.success:
                self._cleanup_helper_session()
                return result

            self.injector = injector
            self.started = True
            self.launched_process = result.launched_process
            return result
        except Exception as exc:
            self._signal_helper_stop()
            self._cleanup_helper_session()
            return GameOverlayResult(
                success=False,
                message=f"관리자 권한 game-overlay helper 시작 실패: {exc}",
                fatal=True,
            )

    def stop(self) -> GameOverlayResult:
        if self.injector is None and self.helper_command_path is None and not self.started:
            return GameOverlayResult(success=True, message="game-overlay-sdk 관리자 helper가 시작되어 있지 않습니다.")

        clear_result = self.clear()
        stop_error = ""
        helper_exited = True
        try:
            self._signal_helper_stop()
        except Exception as exc:
            stop_error = str(exc)
        if self.helper_pid > 0:
            helper_exited = wait_for_process_exit(self.helper_pid, HELPER_STOP_TIMEOUT_SECONDS)

        messages: list[str] = []
        success = True
        if clear_result.message and not clear_result.success:
            messages.append(clear_result.message)
            success = False
        if stop_error:
            messages.append(f"관리자 권한 helper 종료 요청 실패: {stop_error}")
            success = False
        if not helper_exited:
            messages.append("관리자 권한 helper가 시간 안에 종료되지 않았습니다.")
            success = False
        if not messages:
            messages.append("game-overlay-sdk 관리자 helper 종료 완료")

        self.started = False
        self.launched_process = False
        self.injector = None
        self._cleanup_helper_session()
        return GameOverlayResult(success=success, message="\n".join(messages))

    @staticmethod
    def _helper_launch_command(
        settings_path: Path,
        response_path: Path,
        command_path: Path,
        parent_pid: int,
    ) -> tuple[str, str]:
        helper_args = [
            CLI_ARG_GAME_OVERLAY_HELPER,
            CLI_ARG_GAME_OVERLAY_HELPER_SETTINGS,
            str(settings_path),
            CLI_ARG_GAME_OVERLAY_HELPER_RESPONSE,
            str(response_path),
            CLI_ARG_GAME_OVERLAY_HELPER_COMMAND,
            str(command_path),
            CLI_ARG_GAME_OVERLAY_HELPER_PARENT_PID,
            str(int(parent_pid)),
        ]
        if getattr(sys, "frozen", False):
            executable = sys.executable
            parameters = helper_args
        else:
            executable = sys.executable
            parameters = [str(Path(__file__).resolve().parent / "main_entry.py"), *helper_args]
        return str(executable), subprocess.list2cmdline(parameters)

    @staticmethod
    def _wait_for_helper_response(response_path: Path) -> dict[str, Any] | None:
        deadline = time.monotonic() + HELPER_RESPONSE_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if response_path.exists():
                try:
                    return json.loads(response_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
            time.sleep(HELPER_POLL_INTERVAL_SECONDS)
        return None

    def _signal_helper_stop(self) -> None:
        if self.helper_command_path is None:
            return
        write_json_file(self.helper_command_path, {"command": "stop"})

    def _cleanup_helper_session(self) -> None:
        session_dir = self.helper_dir
        self.helper_dir = None
        self.helper_settings_path = None
        self.helper_response_path = None
        self.helper_command_path = None
        self.helper_pid = 0
        if session_dir is not None:
            shutil.rmtree(session_dir, ignore_errors=True)


def run_game_overlay_helper_from_args(args: list[str]) -> int:
    settings_arg = read_cli_arg_value(args, CLI_ARG_GAME_OVERLAY_HELPER_SETTINGS)
    response_arg = read_cli_arg_value(args, CLI_ARG_GAME_OVERLAY_HELPER_RESPONSE)
    command_arg = read_cli_arg_value(args, CLI_ARG_GAME_OVERLAY_HELPER_COMMAND)
    parent_pid = int(read_cli_arg_value(args, CLI_ARG_GAME_OVERLAY_HELPER_PARENT_PID) or 0)
    if not settings_arg or not response_arg or not command_arg:
        return 1

    settings_path = Path(settings_arg)
    response_path = Path(response_arg)
    command_path = Path(command_arg)

    try:
        settings_data = json.loads(settings_path.read_text(encoding="utf-8"))
        settings = GameOverlaySettings(
            target_process=str(settings_data.get("target_process", DEFAULT_GAME_OVERLAY_TARGET_PROCESS)).strip()
            or DEFAULT_GAME_OVERLAY_TARGET_PROCESS,
            steam_app_id=int(settings_data.get("steam_app_id", DEFAULT_GAME_OVERLAY_STEAM_APP_ID) or 0),
            exe_path=str(settings_data.get("exe_path", "") or "").strip(),
            attach_strategy=str(settings_data.get("attach_strategy", DEFAULT_GAME_OVERLAY_ATTACH_STRATEGY)).strip()
            or DEFAULT_GAME_OVERLAY_ATTACH_STRATEGY,
        )
    except Exception as exc:
        write_json_file(
            response_path,
            {
                "success": False,
                "message": f"관리자 권한 helper 설정 읽기 실패: {exc}",
                "launched_process": False,
                "fatal": True,
                "helper_pid": os.getpid(),
            },
        )
        return 1

    backend = GameOverlayBackend(settings)
    result = backend.start()
    write_json_file(
        response_path,
        {
            "success": result.success,
            "message": result.message,
            "launched_process": result.launched_process,
            "fatal": result.fatal,
            "helper_pid": os.getpid(),
        },
    )
    if not result.success:
        return 0

    try:
        while True:
            if command_path.exists():
                try:
                    command_payload = json.loads(command_path.read_text(encoding="utf-8"))
                    if str(command_payload.get("command", "")).strip().lower() == "stop":
                        break
                except (OSError, json.JSONDecodeError):
                    pass
            if parent_pid > 0 and not process_exists(parent_pid):
                break
            time.sleep(HELPER_POLL_INTERVAL_SECONDS)
    finally:
        backend.stop()
    return 0


def read_cli_arg_value(args: list[str], name: str) -> str:
    prefix = name + "="
    for index, arg in enumerate(args):
        if arg == name and index + 1 < len(args):
            return str(args[index + 1])
        if arg.startswith(prefix):
            return str(arg[len(prefix):])
    return ""


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, int(pid))
    if not handle:
        return False
    try:
        return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def wait_for_process_exit(pid: int, timeout_seconds: float) -> bool:
    if pid <= 0:
        return True
    if os.name != "nt":
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while time.monotonic() < deadline:
            if not process_exists(pid):
                return True
            time.sleep(HELPER_POLL_INTERVAL_SECONDS)
        return not process_exists(pid)

    handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, int(pid))
    if not handle:
        return True
    try:
        timeout_ms = max(0, int(float(timeout_seconds) * 1000.0))
        return ctypes.windll.kernel32.WaitForSingleObject(handle, timeout_ms) != WAIT_TIMEOUT
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
