"""Shared, cross-page application context.

The pages are otherwise independent — each owns its widgets and subscribes
to the daemon-client signals it needs — but two things are genuinely shared:
the ``DaemonClient`` and the on-disk config. This holds both.

**Every config write goes through :meth:`AppContext.write_config`** — no page
calls ``save_config`` itself. There is more than one settings-class page now
(Settings and Automation), and the write is not just a write: it has to
persist, tell the read-only consumers, and nudge the daemon, in that order.
One writer keeps that sequence in one place instead of once per page.
Read-only consumers (the Overview status line, the About page, the sidebar
footer) connect to ``configChanged`` and refresh themselves without knowing
who changed it.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal

from ..core.config import (
    DEFAULT_CONFIG_PATH, AppConfig, load_config, save_config,
)
from . import util
from .dbus_client import DaemonClient


class AppContext(QObject):
    configChanged = Signal()

    def __init__(self, client: DaemonClient, tray_available: bool = True):
        super().__init__()
        self.client = client
        # Whether a system tray exists this session. The window/tray behaviour
        # settings only bite with a tray, so Settings dims them without one.
        self.tray_available = tray_available
        # None until the first successful load_config; every reader either
        # guards or goes through write_config, which loads on demand.
        self.cfg: AppConfig | None = None  # pylint: disable=disallowed-name  # public attribute read by gui/pages/*.py and gui/tray.py outside this module; renaming it is a separate, coordinated cross-module change

    @property
    def persistent(self) -> bool:
        """True when the desk stays connected (vs. connect-on-demand)."""
        return self.cfg is not None and self.cfg.desk.connection == "persistent"

    def reload_config(self) -> str | None:
        """Reload config from disk into ``cfg`` and notify consumers.

        Returns an error string on failure (leaving the previous ``cfg`` in
        place, and *not* emitting ``configChanged``) so the caller can show a
        dialog; returns ``None`` on success."""
        try:
            self.cfg = load_config(DEFAULT_CONFIG_PATH)
        except Exception as error:  # ConfigError — surface but keep the UI usable
            return str(error)
        util.set_height_unit(self.cfg.ui.units)
        self.configChanged.emit()
        return None

    def write_config(self, mutate: Callable[[AppConfig], None]) -> str | None:
        """Apply ``mutate`` to the config, persist it, and publish the change.

        The single config writer for the whole GUI. ``mutate`` receives the
        live ``cfg`` and sets fields on it; this method owns everything around
        that — saving with ``tomlkit`` (so the user's comments and formatting
        survive), emitting ``configChanged`` for the read-only pages, and
        nudging the daemon.

        Returns an error string on failure, ``None`` on success. A failed save
        leaves ``cfg`` mutated in memory on purpose: the widgets still show what
        the user typed, so they can fix the cause and save again rather than
        silently losing the edit.
        """
        if self.cfg is None:
            err = self.reload_config()
            if err is not None:
                return err
        # reload_config sets cfg whenever it returns None, so this holds —
        # but it holds across a call, so state it here rather than assume it.
        config = self.cfg
        if config is None:
            return "config unavailable"
        mutate(config)
        try:
            save_config(config, DEFAULT_CONFIG_PATH)
        except Exception as error:
            return str(error)
        # Before the signal, not after: a consumer redrawing a height in
        # response to configChanged has to see the unit the same write chose.
        util.set_height_unit(config.ui.units)
        # Read-only consumers (footer, overview status) reflect the change.
        self.configChanged.emit()
        # The daemon hot-reloads on file change; nudge it anyway in case
        # it's watching a different path.
        if self.client.available:
            self.client.reload_config()
        return None
