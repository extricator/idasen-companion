"""``STATUS_LABELS`` must not drift from ``Status``.

``gui/util.py`` maps every wire-format status value to a translated label by
hand, alongside the ``Status`` enum in ``core/machine.py``. A future status
value that ships without a label degrades gracefully at runtime
(``status_label()`` falls back to the raw wire value), but that fallback is a
silent regression, not a feature — this guards it at test time instead.

Skipped where PySide6 is missing, since the RPM lists it as a runtime
``Requires`` rather than a ``BuildRequires`` and the spec's ``%check`` may run
this suite without it.
"""

import pytest

pytest.importorskip("PySide6.QtCore", reason="GUI util module needs PySide6")

import os

# Forced, not defaulted. A desktop session exports QT_QPA_PLATFORM (xcb here),
# which the RPM build inherits — and then aborts, because the build sandbox
# can't reach that display. Tests must not depend on an ambient one.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from idasen_companion.core.machine import Status  # noqa: E402
from idasen_companion.gui.util import STATUS_LABELS  # noqa: E402


def test_every_status_has_a_label():
    assert set(STATUS_LABELS) == {s.value for s in Status}
