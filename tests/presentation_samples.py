"""A table of *inputs*, not of expected outputs, for every public
``Formatter`` method.

The expectations live elsewhere — in ``tests/test_golden_presentation_contract.py``'s
hand-typed three-column table for the four moment renderers, and in that same
module's backend-equality assertions for everything else. This module exists
so that table and the isolated-subprocess callability leg in
``tests/test_qt_free_imports.py`` read the **same** list of
``(method, args, kwargs)`` invocations, rather than each keeping its own copy
that could quietly drift out of step with the other.

This module must stay importable from a process that has never loaded a
windowing toolkit — the PRES-01 subprocess gate imports it directly, in a
fresh interpreter, before anything else has had a chance to pull one in. So
nothing here imports a GUI toolkit, transitively or otherwise, and nothing
reads the system clock: every ``datetime`` below is a frozen literal, the
same discipline the golden module's own four-helper table follows and for
the same reason — see that module's docstring.
"""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

from idasen_companion.core.machine import DeskState
from idasen_companion.core.presentation.english import EnglishTranslator
from idasen_companion.core.presentation.formatter import (
    Formatter, PresentationContext,
)
from idasen_companion.core.presentation.specs import TimeStyle
from idasen_companion.core.presentation.gettext_translator import (
    GettextTranslator,
)
from idasen_companion.core.presentation.plain_locale import PlainLocaleFormatter
from idasen_companion.core.units import HeightUnit

#: The one moment every "afternoon" case below renders — chosen to land
#: outside noon in a 12-hour rendering (this is GATE-08's own cross-check
#: instant, matching the committed vocabulary goldens) and the one
#: "morning" case, chosen so the two together exercise a 12-hour backend's
#: AM and PM branches, not just one of them.
AFTERNOON = datetime(2026, 8, 17, 14, 32)
MORNING = datetime(2026, 8, 17, 9, 5)

#: One representative height, in metres, reused across every height-shaped
#: sample below -- and by the golden module's own hand-typed contract
#: table -- so a reader only has to learn one number, and the two tables
#: cannot end up pinning two different heights.
HEIGHT_METERS = 1.105


class Sample(NamedTuple):
    """One canonical invocation: a case name, a ``Formatter`` method name,
    and the positional/keyword arguments to call it with.

    ``case`` is a short, readable label distinct from ``method`` wherever a
    method needs more than one row (``connection_phrases``, ``clock``) — a
    failing assertion then names which branch or which moment broke, not
    just which method.
    """

    case: str
    method: str
    args: tuple[object, ...]
    kwargs: dict[str, object]


#: One row per public ``Formatter`` method, covering every method named in
#: this plan's own interfaces list. ``connection_phrases`` carries three rows
#: — one per branch its wire-value lookup can take — and ``clock`` carries
#: two, at :data:`AFTERNOON` and :data:`MORNING`, so a 12-hour backend's two
#: halves both get exercised by at least one row.
SAMPLES: tuple[Sample, ...] = (
    Sample("height_value", "height_value", (HEIGHT_METERS,), {}),
    Sample("height", "height", (HEIGHT_METERS,), {}),
    Sample("preset_tick", "preset_tick",
           ("Sit", HEIGHT_METERS), {"trim": True}),
    Sample("connection_phrases_connected", "connection_phrases",
           (True, True, False), {}),
    Sample("connection_phrases_disconnected", "connection_phrases",
           (False, False, False), {}),
    Sample("connection_phrases_on_demand", "connection_phrases",
           (False, True, False), {}),
    Sample("status_label", "status_label", ("active",), {}),
    Sample("status_head", "status_head", ("active",), {}),
    Sample("position_label", "position_label", ("sitting",), {}),
    Sample("preset_label", "preset_label", ("sit",), {}),
    Sample("trigger_label", "trigger_label", ("automation",), {}),
    Sample("pre_move_summary", "pre_move_summary",
           (DeskState.STANDING, 3900), {}),
    Sample("pre_move_body", "pre_move_body", (), {}),
    Sample("snooze_action_label", "snooze_action_label", (15,), {}),
    Sample("skip_action_label", "skip_action_label", (), {}),
    Sample("automation_paused_summary", "automation_paused_summary", (), {}),
    Sample("automation_paused_body", "automation_paused_body", (), {}),
    Sample("move_failed_summary", "move_failed_summary",
           (DeskState.STANDING,), {}),
    Sample("move_failed_body", "move_failed_body", ("offline",), {}),
    Sample("try_now_action_label", "try_now_action_label", (), {}),
    Sample("later_label", "later_label", (), {}),
    Sample("snooze_line", "snooze_line", ("14:32",), {}),
    Sample("due_now_label", "due_now_label", (), {}),
    # Not 1, so the singular form (covered by test_words.py's own dedicated
    # assertion, not by this table) is never the row exercised here.
    Sample("minutes_label", "minutes_label", (5,), {}),
    Sample("position_or_custom", "position_or_custom", ("standing",), {}),
    Sample("countdown", "countdown", (125,), {}),
    Sample("day_label", "day_label", ("mon",), {}),
    Sample("fmt_days", "fmt_days", (["mon", "tue", "wed"],), {}),
    Sample("duration_verbose", "duration_verbose", (3900,), {}),
    Sample("duration_hm", "duration_hm", (3900,), {}),
    Sample("duration", "duration", (45,), {}),
    Sample("duration_minutes", "duration_minutes", (600,), {}),
    Sample("day_short", "day_short", (AFTERNOON,), {}),
    Sample("day_heading", "day_heading", (AFTERNOON,), {}),
    Sample("clock_afternoon", "clock", (AFTERNOON,), {}),
    Sample("clock_morning", "clock", (MORNING,), {}),
    Sample("day_and_clock", "day_and_clock", (AFTERNOON,), {}),
)

#: Every public ``Formatter`` member deliberately absent from :data:`SAMPLES`,
#: with the reason it is not a formatter written down beside it — the three
#: capability accessors, and the four helpers that hand back a bare number
#: rather than rendered text.
NOT_FORMATTERS: dict[str, str] = {
    "context": "a capability accessor returning the injected "
               "PresentationContext itself, not rendered text",
    "unit": "a capability accessor returning the injected HeightUnit, "
            "not rendered text",
    "time_style": "a capability accessor returning the injected TimeStyle, "
                  "not rendered text",
    "to_display_height": "returns a bare float conversion, never rendered "
                          "text",
    "from_display_height": "the inverse of to_display_height; also a bare "
                            "float, never rendered text",
    "height_decimals": "returns a bare int, never rendered text",
    "height_step": "returns a bare float, never rendered text",
}


def build_plain_formatter() -> Formatter:
    """The **journal's** Qt-free ``Formatter`` pairing: the fixed-policy
    locale backend paired with the pass-through English translator, at
    centimetres — the same pair
    :func:`idasen_companion.core.presentation.english.format_duration_human`
    builds for the journal, reused here so both callers of this table
    construct the Qt-free side identically. ``docs/LOGGING.md``'s stable,
    greppable English promise is what keeps this pairing worth its own
    coverage rather than being folded into :func:`build_daemon_formatter`.
    """
    return Formatter(PresentationContext(
        locale=PlainLocaleFormatter(), translator=EnglishTranslator(),
        unit=HeightUnit.CENTIMETRES,
        time_style=TimeStyle.HOUR_AND_MINUTE))


def build_daemon_formatter() -> Formatter:
    """The Qt-free ``Formatter`` the daemon actually builds: the fixed-policy
    locale backend paired with ``GettextTranslator`` — the pairing
    ``daemon/main.py``'s ``_build_formatter`` constructs for real. The unit
    is fixed at centimetres here, the same simplification
    :func:`build_plain_formatter` already makes, while the real one resolves
    it from config. ``GettextTranslator`` reads the process-wide gettext
    catalog at call time, so this must be both constructed *and* rendered
    inside the same language context that binds that catalog —
    ``tests/test_golden_presentation_contract.py``'s ``_language(...)`` block
    is where that discipline is kept.
    """
    return Formatter(PresentationContext(
        locale=PlainLocaleFormatter(), translator=GettextTranslator(),
        unit=HeightUnit.CENTIMETRES,
        time_style=TimeStyle.HOUR_AND_MINUTE))
