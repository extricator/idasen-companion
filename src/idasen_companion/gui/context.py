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

import os
from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from ..core.config import (
    DEFAULT_CONFIG_PATH, AppConfig, load_config, save_config,
)
from ..core.presentation.formatter import Formatter, PresentationContext
from ..core.presentation.gettext_translator import GettextTranslator
from ..core.units import UnitSetting, resolve_height_unit
from .dbus_client import DaemonClient
from .i18n import apply_language, resolve_locale
from .locale_backend import QtLocaleFormatter


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
        # Built from AppConfig()'s defaults, the same way cfg starts
        # None-then-loaded — nothing may read a half-built context before the
        # first reload_config()/write_config() rebuilds this from the real
        # on-disk config.
        self.fmt: Formatter = self._build_formatter(AppConfig())

    def _build_formatter(self, config: AppConfig) -> Formatter:
        """The one place ``config`` becomes a :class:`Formatter`.

        Shared by the constructor, :meth:`reload_config` and
        :meth:`write_config` so the three construction points read one
        expression rather than three copies of it.

        A display language is not a statement about measurement. The
        environment is not a guess here — it is the only signal that
        actually describes the user's country. ``core/units.py``'s own
        module docstring lists the intended order (``language`` when it
        names a territory, then ``LC_ALL``, ``LC_MEASUREMENT``, ``LANG``,
        ``LANGUAGE``); passing the resolved locale's name manufactures a
        territory (``"es"`` -> ``"es_ES"``) that was never in the setting,
        defeating that order. Passing the raw setting is exactly what
        ``daemon/main.py``'s ``_build_formatter`` already does, so the two
        front ends now share one call shape and cannot drift apart again.
        """
        locale = resolve_locale(config.ui.language)
        unit = resolve_height_unit(
            UnitSetting(config.ui.units), language=config.ui.language,
            environ=os.environ)
        context = PresentationContext(
            locale=QtLocaleFormatter(locale),
            translator=GettextTranslator(), unit=unit)
        return Formatter(context)

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
        apply_language(QApplication.instance(), self.cfg.ui.language)
        self.fmt = self._build_formatter(self.cfg)
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
        # response to configChanged has to see the unit — and, from here on,
        # the language — the same write chose.
        apply_language(QApplication.instance(), config.ui.language)
        self.fmt = self._build_formatter(config)
        # Read-only consumers (footer, overview status) reflect the change.
        self.configChanged.emit()
        # The daemon hot-reloads on file change; nudge it anyway in case
        # it's watching a different path.
        if self.client.available:
            self.client.reload_config()
        return None
