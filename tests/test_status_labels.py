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

from idasen_companion.core.machine import Status
from idasen_companion.core.i18n import STATUS_LABELS


def test_every_status_has_a_label():
    assert set(STATUS_LABELS) == {s.value for s in Status}
