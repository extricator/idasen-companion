"""About page: app identity, links, and system info for bug reports."""

from __future__ import annotations

from ...core.i18n import pgettext

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
from .. import restyle
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
        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        scroll, outer = page_scroll()
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

        def _restyle_version_label(target: QLabel = version_label) -> None:
            target.setStyleSheet(f"color: {css(theme().secondary)}; border: none;")

        restyle.register(version_label, _restyle_version_label)
        name_row.addWidget(name, 0, Qt.AlignmentFlag.AlignBaseline)
        name_row.addWidget(version_label, 0, Qt.AlignmentFlag.AlignBaseline)
        name_row.addStretch()
        title_col.addLayout(name_row)
        tagline = QLabel(pgettext('about', "Sit/stand desk automation"))

        def _restyle_tagline(target: QLabel = tagline) -> None:
            target.setStyleSheet(f"color: {css(theme().secondary)}; border: none;")

        restyle.register(tagline, _restyle_tagline)
        title_col.addWidget(tagline)

        links = QHBoxLayout()
        links.setSpacing(8)
        project_btn = QPushButton(pgettext('about', "Project page"))
        project_btn.clicked.connect(lambda: self._open_url(HOMEPAGE))
        issue_btn = QPushButton(pgettext('about', "Report an issue"))
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
        about.body.addWidget(section_label(pgettext('about', "About")))
        desc = QLabel(pgettext('about', "Keeps your Idasen desk alternating sit / stand on a schedule, "
            "with presets and activity tracking."))
        desc.setWordWrap(True)
        desc.setStyleSheet("border: none;")
        about.body.addWidget(desc)
        meta = QLabel(pgettext('about', "GNU GPL v3 or later · © extricator"))

        def _restyle_meta(target: QLabel = meta) -> None:
            target.setStyleSheet(f"color: {css(theme().secondary)}; border: none;")

        restyle.register(meta, _restyle_meta)
        about.body.addWidget(meta)
        credit = QLabel(pgettext('about', "Built on idasen · bleak · PySide6 / Qt"))

        def _restyle_credit(target: QLabel = credit) -> None:
            target.setStyleSheet(f"color: {css(theme().muted)}; border: none;")

        restyle.register(credit, _restyle_credit)
        about.body.addWidget(credit)
        outer.addWidget(about)

        # ----- global shortcuts -----
        shortcuts = Card()
        shortcuts.body.addWidget(section_label(pgettext('about', "Global shortcuts")))
        intro = QLabel(pgettext('about', "Bind these commands to keys in your desktop's own keyboard "
            "settings — reliable on X11 and Wayland, on every desktop:"))
        intro.setWordWrap(True)

        def _restyle_intro(target: QLabel = intro) -> None:
            target.setStyleSheet(f"color: {css(theme().muted)}; border: none;")

        restyle.register(intro, _restyle_intro)
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

        def _restyle_commands(target: QLabel = commands) -> None:
            target.setStyleSheet(f"color: {css(theme().text)}; border: none;")

        restyle.register(commands, _restyle_commands)
        shortcuts.body.addWidget(commands)
        outer.addWidget(shortcuts)

        # ----- system -----
        system = Card()
        head = QHBoxLayout()
        head.addWidget(section_label(pgettext('about', "System")))
        head.addStretch()
        self._copy_btn = QPushButton(pgettext('about', "Copy"))
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setToolTip(pgettext('about', "Copy this system info for bug reports"))
        self._copy_btn.clicked.connect(self._copy_about)
        head.addWidget(self._copy_btn)
        system.body.addLayout(head)

        # Each field is (stable id used for lookup, translated display label).
        # The id stays English so _refresh() lookups don't depend on locale;
        # only the shown label goes through tr().
        self._fields: dict[str, QLabel] = {}
        rows = (
            ("App version", pgettext('about', "App version")),
            ("Daemon", pgettext('about', "Daemon")),
            ("Desk", pgettext('about', "Desk")),
            ("Idle detection", pgettext('about', "Idle detection")),
            ("Config", pgettext('about', "Config")),
            ("Libraries", pgettext('about', "Libraries")),
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
        field_row = QWidget()
        hbox = QHBoxLayout(field_row)
        hbox.setContentsMargins(2, 6, 2, 6)
        hbox.setSpacing(12)
        key_label = QLabel(label)
        # Size the key column from the widest label at the current font, so
        # it never clips (e.g. "Idle detection") at larger fonts / locales.
        key_label.setFixedWidth(
            key_label.fontMetrics().horizontalAdvance(
                pgettext('about', "Idle detection")) + 12)

        def _restyle_key_label(target: QLabel = key_label) -> None:
            target.setStyleSheet(f"color: {css(theme().muted)}; border: none;")

        restyle.register(key_label, _restyle_key_label)
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
            (pgettext('about', "running · %s") % __version__) if available
            else pgettext('about', "not running"))
        if config and config.desk.mac:
            mode = (pgettext('about', "persistent") if config.desk.connection == "persistent"
                    else pgettext('about', "on demand"))
            self._fields["Desk"].setText(
                pgettext('about', "%(mac)s · %(mode)s")
                % {"mac": config.desk.mac, "mode": mode})
        else:
            self._fields["Desk"].setText(pgettext('about', "not configured"))
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
        #
        # The pasted block's field names render in English in every
        # language, deliberately: this blob exists to be pasted into a bug
        # report, and a maintainer reading it should not have to
        # reverse-translate a field name to know what it names. The values
        # stay in whatever language the UI is in, because they are what the
        # user is looking at. That split is possible only because the loop
        # below reads the stable lookup id `_fields` is keyed by, not the
        # translated label shown beside it in the UI (see the comment above
        # `_fields` in `_build`). This is a deliberate decision, not an
        # oversight left over from how the field map happens to be keyed --
        # do not "fix" it by swapping in the translated label.
        lines = [f"Idasen Companion {__version__}"]
        lines += [f"{key}: {value.text()}"
                  for key, value in self._fields.items()]
        # Each line here is already whatever it is going to be -- the app
        # name and version above, a stable field name paired with its
        # already-rendered value below. Stacking them with a line break
        # apiece lays the blob out; it does not build a sentence out of
        # translated pieces, so only the order is fixed in code.
        QGuiApplication.clipboard().setText("\n".join(lines))
        self._copy_btn.setText(pgettext('about', "Copied"))
        QTimer.singleShot(1500, lambda: self._copy_btn.setText(pgettext('about', "Copy")))

    @staticmethod
    def _open_url(url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))
