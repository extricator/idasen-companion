"""Qt-free entry point for the shared GUI and daemon command."""

from __future__ import annotations

import importlib.util
import sys

from . import cli


def main(argv: list[str] | None = None) -> int:
    """Route GUI launches only after recognizing their complete argument list."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments == ["--window"]:
        if importlib.util.find_spec("PySide6") is None:
            print("idasen-companion: GUI unavailable; a subcommand is required "
                  "in the headless package", file=sys.stderr)
            return 2
        from .gui.main import main as gui_main  # pylint: disable=import-outside-toplevel

        return gui_main(arguments)
    return cli.main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
