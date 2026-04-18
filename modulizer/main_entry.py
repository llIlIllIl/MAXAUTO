from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from modulizer.system import enable_dpi_awareness
else:
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
    debug_mode = "--debug" in args
    enable_dpi_awareness()
    main_app = _load_main_app()
    root = tk.Tk()
    main_app(root, debug_mode=debug_mode)
    root.mainloop()


if __name__ == "__main__":
    main()
