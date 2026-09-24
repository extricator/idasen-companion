"""``AppContext.fmt``: a built ``Formatter``, rebuilt before every signal.

Skipped where PySide6 is missing, and forces the offscreen platform before
any ``QtWidgets`` import -- see ``tests/test_settings_form.py`` for why both
matter.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

import os  # noqa: E402

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QLocale  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from idasen_companion.core.config import AppConfig, save_config  # noqa: E402
from idasen_companion.core.display_prefs import HeightUnit  # noqa: E402
from idasen_companion.gui import context as context_mod  # noqa: E402
from idasen_companion.gui.context import AppContext  # noqa: E402

MAC = "E1:B2:C3:D4:E5:F6"


class FakeClient:
    """Enough DaemonClient for AppContext: never available, so no D-Bus."""

    available = False

    def reload_config(self):  # pragma: no cover - unreachable while unavailable
        raise AssertionError("should not nudge an unavailable daemon")


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _restore_default_locale(qapp):
    yield
    QLocale.setDefault(QLocale("en_US"))


@pytest.fixture
def config_path(tmp_path):
    return tmp_path / "config.toml"


@pytest.fixture
def ctx(qapp, config_path, monkeypatch):
    # Pinned to "cm" explicitly, rather than left at the "system" default:
    # the ordering test below needs a starting unit that provably differs
    # from what it writes, and "system" resolves against the *host's* own
    # locale environment (see resolve_height_unit), which would make that
    # test pass or fail depending on the machine running the suite.
    cfg = AppConfig()
    cfg.desk.mac = MAC
    cfg.ui.units = "cm"
    save_config(cfg, config_path)
    monkeypatch.setattr(context_mod, "DEFAULT_CONFIG_PATH", config_path)
    return AppContext(FakeClient(), tray_available=True)


def test_a_freshly_constructed_context_has_a_formatter(qapp):
    """Before any config is loaded, ``fmt`` is already built -- nothing may
    read a half-built context.

    ``[ui] units`` defaults to "system", which resolves against ``QLocale``'s
    own cached system-locale singleton, so this only asserts that ``fmt`` is
    a real, usable ``Formatter`` rather than pinning which unit "system"
    happens to resolve to on the host running the suite.
    """
    ctx = AppContext(FakeClient())
    assert isinstance(ctx.fmt.unit, HeightUnit)


def test_write_config_setting_inches_produces_a_formatter_in_inches(ctx):
    err = ctx.write_config(lambda cfg: setattr(cfg.ui, "units", "in"))
    assert err is None
    assert ctx.fmt.unit == HeightUnit.INCHES


def test_write_config_mutating_the_unit_rebuilds_a_new_formatter_object(ctx):
    first = ctx.fmt
    err = ctx.write_config(lambda cfg: setattr(cfg.ui, "units", "in"))
    assert err is None
    assert ctx.fmt is not first


def test_reload_config_setting_inches_produces_a_formatter_in_inches(
        ctx, config_path):
    cfg = AppConfig()
    cfg.desk.mac = MAC
    cfg.ui.units = "in"
    save_config(cfg, config_path)
    err = ctx.reload_config()
    assert err is None
    assert ctx.fmt.unit == HeightUnit.INCHES


def test_config_changed_observers_see_the_already_new_formatter(ctx):
    """The rebuild must land before ``configChanged`` reaches its consumers —
    a handler connected to the signal has to observe the post-write unit,
    never the pre-write one."""
    # Loaded first so write_config's own mutate/save/emit is the only
    # configChanged this test observes -- write_config's cfg-is-None branch
    # (the very first load) emits once on its own via reload_config.
    assert ctx.reload_config() is None
    observed = []
    ctx.configChanged.connect(lambda: observed.append(ctx.fmt.unit))

    err = ctx.write_config(lambda cfg: setattr(cfg.ui, "units", "in"))

    assert err is None
    assert observed == [HeightUnit.INCHES]
