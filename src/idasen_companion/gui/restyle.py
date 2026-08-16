"""Re-apply theme-derived styling after the desktop palette changes.

Every ``setStyleSheet(...)`` call that bakes a :func:`.theme.theme` value
into a string does so once, at construction, and is never re-run. This
module is the mechanism that fixes that: a widget registers the callable
that rebuilds its own styling, and a single trigger walks every registered
callable whenever the application palette changes.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

_registry: dict[int, Callable[[], None]] = {}
_next_token = itertools.count()


def register(owner: QObject, restyler: Callable[[], None]) -> None:
    """Apply ``restyler`` now, and again on every future :func:`sweep`.

    ``restyler`` is called once immediately, so a call site never needs to
    invoke it itself before registering. The entry is dropped automatically
    once ``owner`` is destroyed, so a widget torn down by
    :func:`.widgets.clear_layout` (or anything else) stops being swept
    without its caller having to remember to deregister it.
    """
    token = next(_next_token)
    _registry[token] = restyler
    restyler()

    def _forget() -> None:
        # Closes over `token` and the module registry only -- never over
        # `owner`, which would keep the very object being destroyed alive
        # for the duration of this call.
        _registry.pop(token, None)

    owner.destroyed.connect(_forget)


def sweep() -> None:
    """Re-run every registered restyler.

    Iterates a snapshot: a restyler is allowed to construct a widget that
    registers itself, and an owner's `destroyed` signal can land mid-sweep.
    Mutating `_registry` while iterating it directly would raise.
    """
    for restyler in list(_registry.values()):
        restyler()


def follow_palette(application: QApplication) -> None:
    """Run :func:`sweep` whenever the application palette changes.

    Wired through this named function, rather than connected inline at the
    call site, because the signal it rests on today is deprecated in Qt 6 in
    favour of an application-palette-change event delivered through
    `QObject.event()` -- deprecated, but present and firing in the bundled
    Qt. Isolating the connection here gives the test suite one seam to
    assert the behaviour ("changing the application palette runs every
    registered restyler") instead of the signal's name, so the day it stops
    firing, a test goes red and the fix is this function's body, not a hunt
    across every call site that connected to it directly.
    """
    application.paletteChanged.connect(sweep)


def reset_registry_for_tests() -> None:
    """Empty the registry.

    For use only by test fixtures, so one test module's registrations
    cannot leak into another's sweep count. Not part of this module's
    public surface for anything other than tests.
    """
    _registry.clear()
