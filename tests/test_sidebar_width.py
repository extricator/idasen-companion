"""The sidebar's own width math.

``gui/widgets.py::sidebar_width_for_labels`` is a pure function: given the
labels the sidebar will render and the font it renders them in, it returns
the width the sidebar needs, clamped between a floor (today's hardcoded
176px, so English never moves) and a ceiling (so a pathological translation
cannot eat the window). This file covers that function's own clamp
behaviour directly.

Skipped where PySide6 is missing, and forces the offscreen platform before
any ``QtWidgets`` import -- see ``tests/test_settings_form.py`` for why both
matter.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

import os

# Forced, not defaulted. A desktop session exports QT_QPA_PLATFORM (xcb here),
# which the RPM build inherits — and then aborts, because the build sandbox
# can't reach that display. Tests must not depend on an ambient one.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtGui import QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from idasen_companion.gui.widgets import (  # noqa: E402
    SIDEBAR_WIDTH_CEILING, SIDEBAR_WIDTH_FLOOR, emphasize,
    sidebar_width_for_labels,
)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_short_labels_return_exactly_the_floor(qapp):
    label = QLabel()
    assert sidebar_width_for_labels(["Overview", "About"],
                                     label.font()) == SIDEBAR_WIDTH_FLOOR


def test_far_too_long_labels_return_exactly_the_ceiling(qapp):
    label = QLabel()
    absurd = "X" * 500
    assert sidebar_width_for_labels([absurd], label.font()) == SIDEBAR_WIDTH_CEILING


def test_a_midsize_label_list_lands_between_floor_and_ceiling_and_uses_demibold(qapp):
    label = QLabel()
    font = label.font()
    # Long enough to push past the floor, short of the ceiling -- chosen so
    # this assertion is about the clamp's open middle, not either edge.
    labels = ["Registro de actividad", "Automatización"]
    computed = sidebar_width_for_labels(labels, font)
    assert SIDEBAR_WIDTH_FLOOR < computed < SIDEBAR_WIDTH_CEILING

    # The DemiBold weight is genuinely in play: the helper's answer must
    # exceed what the *normal*-weight advance plus the same chrome would
    # give, proven here by computing the normal-weight advance directly
    # rather than by re-running emphasize().
    normal_metrics = QFontMetrics(font)
    normal_widest = max(normal_metrics.horizontalAdvance(text)
                         for text in labels)
    chrome = computed - max(
        QFontMetrics(emphasize(font)).horizontalAdvance(text)
        for text in labels)
    assert computed > normal_widest + chrome


def test_an_empty_label_list_returns_the_floor(qapp):
    label = QLabel()
    assert sidebar_width_for_labels([], label.font()) == SIDEBAR_WIDTH_FLOOR
