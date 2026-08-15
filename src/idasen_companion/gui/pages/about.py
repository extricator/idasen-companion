"""About page: app identity, links, and system info for bug reports."""

from __future__ import annotations

from importlib.metadata import (
    PackageNotFoundError, packages_distributions, version,
)
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QDesktopServices, QFont, QFontDatabase, QGuiApplication,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ... import APP_ID, __version__
from ...core.config import DEFAULT_CONFIG_PATH
from ..theme import css, theme
from ..widgets import Card, icon, page_scroll, section_label, separator
from .base import Page

HOMEPAGE = "https://github.com/extricator/idasen-companion"


class AboutPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        self._build()

    def on_shown(self) -> None:
        self._refresh()

    def _build(self) -> None:
        tokens = theme()
        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        scroll, outer = page_scroll(tokens.window)
        wrapper.addWidget(scroll)

        # ----- hero -----
        hero = Card()
        hrow = QHBoxLayout()
        hrow.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(icon(APP_ID, "input-tablet").pixmap(
            QSize(48, 48), self.devicePixelRatio()))
        logo.setStyleSheet("border: none;")
        hrow.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)

        title_col = QVBoxLayout()
        title_col.setSpacing(3)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name = QLabel("Idasen Companion")
        name_font = name.font()
        name_font.setPointSizeF(name_font.pointSizeF() * 1.5)
        name_font.setWeight(QFont.Weight.DemiBold)
        name.setFont(name_font)
        name.setStyleSheet("border: none;")
        version_label = QLabel(f"v{__version__}")
        version_label.setStyleSheet(
            f"color: {css(tokens.secondary)}; border: none;")
        name_row.addWidget(name, 0, Qt.AlignmentFlag.AlignBaseline)
        name_row.addWidget(version_label, 0, Qt.AlignmentFlag.AlignBaseline)
        name_row.addStretch()
        title_col.addLayout(name_row)
        tagline = QLabel(self.tr("Sit/stand desk automation"))
        tagline.setStyleSheet(f"color: {css(tokens.secondary)}; border: none;")
        title_col.addWidget(tagline)

        links = QHBoxLayout()
        links.setSpacing(8)
        project_btn = QPushButton(self.tr("Project page"))
        project_btn.clicked.connect(lambda: self._open_url(HOMEPAGE))
        issue_btn = QPushButton(self.tr("Report an issue"))
        issue_btn.clicked.connect(
            lambda: self._open_url(f"{HOMEPAGE}/issues"))
        for btn in (project_btn, issue_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            links.addWidget(btn)
        links.addStretch()
        title_col.addSpacing(2)
        title_col.addLayout(links)
        hrow.addLayout(title_col, 1)
        hero.body.addLayout(hrow)
        outer.addWidget(hero)

        # ----- about -----
        about = Card()
        about.body.addWidget(section_label(self.tr("About")))
        desc = QLabel(self.tr(
            "Keeps your Idasen desk alternating sit / stand on a schedule, "
            "with presets and activity tracking."))
        desc.setWordWrap(True)
        desc.setStyleSheet("border: none;")
        about.body.addWidget(desc)
        meta = QLabel(self.tr("GNU GPL v3 or later · © extricator"))
        meta.setStyleSheet(f"color: {css(tokens.secondary)}; border: none;")
        about.body.addWidget(meta)
        credit = QLabel(self.tr("Built on idasen · bleak · PySide6 / Qt"))
        credit.setStyleSheet(f"color: {css(tokens.muted)}; border: none;")
        about.body.addWidget(credit)
        outer.addWidget(about)

        # ----- global shortcuts -----
        shortcuts = Card()
        shortcuts.body.addWidget(section_label(self.tr("Global shortcuts")))
        intro = QLabel(self.tr(
            "Bind these commands to keys in your desktop's own keyboard "
            "settings — reliable on X11 and Wayland, on every desktop:"))
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {css(tokens.muted)}; border: none;")
        font = intro.font()
        font.setPointSizeF(font.pointSizeF() * 0.88)
        intro.setFont(font)
        shortcuts.body.addWidget(intro)
        commands = QLabel("idasen-companion --toggle\n"
                          "idasen-companion --sit\n"
                          "idasen-companion --stand\n"
                          "idasen-companion --preset NAME")
        commands.setTextFormat(Qt.TextFormat.PlainText)
        commands.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        commands.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        commands.setStyleSheet(f"color: {css(tokens.text)}; border: none;")
        shortcuts.body.addWidget(commands)
        outer.addWidget(shortcuts)

        # ----- system -----
        system = Card()
        head = QHBoxLayout()
        head.addWidget(section_label(self.tr("System")))
        head.addStretch()
        self._copy_btn = QPushButton(self.tr("Copy"))
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setToolTip(self.tr("Copy this system info for bug reports"))
        self._copy_btn.clicked.connect(self._copy_about)
        head.addWidget(self._copy_btn)
        system.body.addLayout(head)

        # Each field is (stable id used for lookup, translated display label).
        # The id stays English so _refresh() lookups don't depend on locale;
        # only the shown label goes through tr().
        self._fields: dict[str, QLabel] = {}
        rows = (
            ("App version", self.tr("App version")),
            ("Daemon", self.tr("Daemon")),
            ("Desk", self.tr("Desk")),
            ("Idle detection", self.tr("Idle detection")),
            ("Config", self.tr("Config")),
            ("Libraries", self.tr("Libraries")),
        )
        for i, (key, label) in enumerate(rows):
            if i:
                system.body.addWidget(separator())
            row, value = self._about_field(label)
            self._fields[key] = value
            system.body.addWidget(row)
        outer.addWidget(system)
        outer.addStretch()

    def _about_field(self, label: str) -> tuple[QWidget, QLabel]:
        tokens = theme()
        field_row = QWidget()
        hbox = QHBoxLayout(field_row)
        hbox.setContentsMargins(2, 6, 2, 6)
        hbox.setSpacing(12)
        key_label = QLabel(label)
        # Size the key column from the widest label at the current font, so
        # it never clips (e.g. "Idle detection") at larger fonts / locales.
        key_label.setFixedWidth(
            key_label.fontMetrics().horizontalAdvance(
                self.tr("Idle detection")) + 12)
        key_label.setStyleSheet(f"color: {css(tokens.muted)}; border: none;")
        value = QLabel("—")
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        value.setStyleSheet("border: none;")
        hbox.addWidget(key_label, 0, Qt.AlignmentFlag.AlignTop)
        hbox.addWidget(value, 1)
        return field_row, value

    @staticmethod
    def _lib_version(module: str) -> str:
        """Version of an importable module, however its distribution is named.

        The argument is an *import* name, which usually doubles as the
        distribution name — but not always, and not for us: install
        ``PySide6-Essentials`` (as the dev venv does) and ``version("PySide6")``
        finds nothing, because no distribution goes by that name. Which package
        provides which import is something the metadata already knows, so ask
        it rather than keep a hand-written map of the exceptions.

        Falls back to the module's own ``__version__`` for anything installed
        without metadata at all, and to "?" when the module isn't there.

        Note that "installed" here includes the single-RPM build's private
        library directory, which its launcher puts on ``sys.path`` before the
        interpreter starts — so every bundled library reports the version the
        package shipped with rather than whatever else the machine has.
        """
        try:
            return version(module)
        except PackageNotFoundError:
            pass
        for dist in packages_distributions().get(module, ()):
            try:
                return version(dist)
            except PackageNotFoundError:
                continue
        try:
            return getattr(__import__(module), "__version__", "?")
        except ImportError:
            return "?"

    def _refresh(self) -> None:
        available = self.client.available
        config = self.ctx.cfg
        self._fields["App version"].setText(__version__)
        self._fields["Daemon"].setText(
            (self.tr("running · %s") % __version__) if available
            else self.tr("not running"))
        if config and config.desk.mac:
            mode = (self.tr("persistent") if config.desk.connection == "persistent"
                    else self.tr("on demand"))
            self._fields["Desk"].setText(f"{config.desk.mac} · {mode}")
        else:
            self._fields["Desk"].setText(self.tr("not configured"))
        self._fields["Idle detection"].setText(
            self.client.idle_provider() if available else "—")
        path = str(DEFAULT_CONFIG_PATH)
        home = str(Path.home())
        if path.startswith(home + "/"):
            path = "~" + path[len(home):]
        self._fields["Config"].setText(path)
        self._fields["Libraries"].setText(
            f"bleak {self._lib_version('bleak')} · "
            f"idasen {self._lib_version('idasen')} · "
            f"PySide6 {self._lib_version('PySide6')}")

    def _copy_about(self) -> None:
        # Fields are already current (refreshed when the page was shown),
        # so copy the shown values rather than re-issuing D-Bus reads.
        lines = [f"Idasen Companion {__version__}"]
        lines += [f"{key}: {value.text()}"
                  for key, value in self._fields.items()]
        QGuiApplication.clipboard().setText("\n".join(lines))
        self._copy_btn.setText(self.tr("Copied"))
        QTimer.singleShot(1500, lambda: self._copy_btn.setText(self.tr("Copy")))

    @staticmethod
    def _open_url(url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))
