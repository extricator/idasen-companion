"""``STATUS_LABELS`` must not drift from ``Status``.

``core/i18n.py`` maps every wire-format status value to a
translated label by hand, alongside the ``Status`` enum in
``core/machine.py``. A future status value that ships without a label
degrades gracefully at runtime (``status_label()`` falls back to the raw wire
value), but that fallback is a silent regression, not a feature — this guards
it at test time instead.

The table used to live in ``gui/util.py`` and this module used to need
PySide6 to read it. It does not any more: the vocabulary is Qt-free now, so
this is a plain ``core/`` test with no import skip and no offscreen platform
to force.
"""

from dataclasses import replace

import pytest

from idasen_companion import cli
from idasen_companion.core.config import AppConfig
from idasen_companion.core.machine import Status
from idasen_companion.core.i18n import GettextTranslator, STATUS_LABELS
from idasen_companion.core.presentation import status_head, status_label
from idasen_companion.core.state_values import UnknownStatus, parse_status


def test_every_status_has_a_label():
    assert set(STATUS_LABELS) == {s.value for s in Status}


@pytest.mark.parametrize("raw", ["", " Future-Status \t"])
def test_status_fallback_keeps_unfamiliar_text_verbatim(raw):
    status = parse_status(raw)
    translator = GettextTranslator()
    assert status_label(translator, status) == raw
    assert status_head(translator, status) == raw


def test_cli_parses_status_only_for_presentation(monkeypatch):
    config = AppConfig()
    fmt = cli._formatter(config)
    render = fmt.status_label
    received = []

    def typed_label(status):
        assert isinstance(status, (Status, UnknownStatus))
        received.append(status)
        return render(status)

    monkeypatch.setattr(fmt, "status_label", typed_label)
    snapshot = cli.StatusSnapshot(
        connected=False, height=0.0, position="sitting", moving=False,
        status="active", active_time=0.0, time_remaining=60.0,
        snooze_until=0.0, daily=())
    cli._status_text(snapshot, fmt, persistent_connection=False)
    assert received == [Status.ACTIVE]
    assert type(snapshot.status) is str
    future = replace(snapshot, status=" Future-Status \t")
    assert "  Status:  Future-Status \t" in cli._status_text(
        future, fmt, persistent_connection=False)
    assert future.status == " Future-Status \t"
