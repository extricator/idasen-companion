"""Base class for the main window's stacked pages."""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QWidget

from ..context import AppContext


class Page(QWidget):
    """A page in the sidebar stack.

    Owns its own widgets and subscribes to the client signals it needs.
    ``MainWindow`` calls :meth:`on_shown` when the page becomes the current
    tab, for pages that reload lazily — any page overriding it."""

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.client = ctx.client

    def on_shown(self) -> None:
        """Called when this page becomes the visible tab. No-op by default."""

    def _status_message(self, text: str, timeout: int = 0) -> None:
        """Show a transient message in the main window's status bar."""
        window = self.window()
        if isinstance(window, QMainWindow):
            window.statusBar().showMessage(text, timeout)
