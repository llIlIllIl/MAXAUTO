from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from modulizer.constants import (
        CLI_ARG_AUTOSTART_MONITOR,
        CLI_ARG_AUTOSTART_MONITOR_WITH_GAME,
        CLI_ARG_DEBUG,
        CLI_ARG_GAME_OVERLAY_HELPER,
        CLI_ARG_SKIP_GAME_OVERLAY_WARNING_ONCE,
    )
    from modulizer.game_overlay_backend import run_game_overlay_helper_from_args
    from modulizer.system import enable_dpi_awareness
else:
    from .constants import (
        CLI_ARG_AUTOSTART_MONITOR,
        CLI_ARG_AUTOSTART_MONITOR_WITH_GAME,
        CLI_ARG_DEBUG,
        CLI_ARG_GAME_OVERLAY_HELPER,
        CLI_ARG_SKIP_GAME_OVERLAY_WARNING_ONCE,
    )
    from .game_overlay_backend import run_game_overlay_helper_from_args
    from .system import enable_dpi_awareness


def _load_main_app() -> type:
    try:
        if __package__ in (None, ""):
            from modulizer.main_window import MainApp
        else:
            from .main_window import MainApp
    except ImportError as exc:
        if getattr(exc, "name", "") == "PIL":
            raise SystemExit("Pillow is required. Install with: py -3.13 -m pip install pillow") from exc
        raise
    return MainApp


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if CLI_ARG_GAME_OVERLAY_HELPER in args:
        raise SystemExit(run_game_overlay_helper_from_args(args))
    debug_mode = CLI_ARG_DEBUG in args
    startup_action: str | None = None
    if CLI_ARG_AUTOSTART_MONITOR_WITH_GAME in args:
        startup_action = "monitor_with_game"
    elif CLI_ARG_AUTOSTART_MONITOR in args:
        startup_action = "monitor"
    skip_game_overlay_warning_once = CLI_ARG_SKIP_GAME_OVERLAY_WARNING_ONCE in args
    enable_dpi_awareness()
    main_app = _load_main_app()
    root = tk.Tk()
    main_app(
        root,
        debug_mode=debug_mode,
        startup_action=startup_action,
        skip_game_overlay_warning_once=skip_game_overlay_warning_once,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
