"""The gettext-flavour register of marked translatable constants.

The pattern already used at ``gui/main_window.py``'s ``NAV_ITEMS``,
``gui/util.py`` and ``gui/background_portal.py``: every translatable
literal lives once, as a module-level constant marked for extraction, and
a formatter references the constant's name rather than writing a string
literal inline. This module is that register for the code under
``core/`` — the half of the app that has no Qt translator to mark
literals with.

Two divergences from the Qt-flavour register are load-bearing.

**No context argument.** ``QT_TRANSLATE_NOOP`` takes a context name because
each ``.ts`` file keeps per-context sections; ``po/idasen_companion.pot`` is
one flat catalog with no such split, so there is nothing for a context
argument to select and :func:`N_`/:func:`NP_` take none.

**One call carries both plural forms.** :func:`NP_` takes the singular and
the plural literal together and returns them as a pair, so
``scripts/build-translations.sh``'s ``--keyword=NP_:1,2`` reads them as one
``(msgid, msgid_plural)`` entry from a single call site — unlike gettext's
own ``ngettext(singular, plural, count)``, which needs both literals again
at every *call*, this register needs them written down exactly once. This
matches Phase 12 D-02's already-committed register shape.

Do not import these markers from ``core/i18n.py`` — that module is the
process-wide gettext lookup, not a place literals are declared, and this is
not the phase to give it that second job.
"""

from __future__ import annotations


def N_(source: str) -> str:  # pylint: disable=invalid-name  # gettext's own extraction-marker convention, not a project abbreviation
    """Mark ``source`` for extraction. Returns it unchanged."""
    return source


def NP_(singular: str, plural: str) -> tuple[str, str]:  # pylint: disable=invalid-name  # gettext's own extraction-marker convention, not a project abbreviation
    """Mark a plural pair for extraction. Returns the pair unchanged."""
    return singular, plural


#: A count of whole hours. Source strings carried over byte-identically from
#: ``daemon/i18n.py``'s pre-merge literals so the extracted msgids match what
#: ``po/es.po`` already holds.
HOURS = NP_("%d hour", "%d hours")

#: A count of whole minutes. Byte-identical to the existing msgid/msgid_plural
#: in ``po/es.po`` — see the module docstring above.
MINUTES = NP_("%d minute", "%d minutes")

#: A count of whole seconds. Byte-identical to the existing msgid/msgid_plural
#: in ``po/es.po`` — see the module docstring above.
SECONDS = NP_("%d second", "%d seconds")

#: Joins two already-whole, already-translated duration messages (an hours
#: message and a minutes message) into one sentence fragment, e.g.
#: "1 hour 5 minutes". Both %(hours)s and %(minutes)s are substituted as
#: complete translated values, never assembled fragments — see
#: ``core/presentation/formatter.py``'s ``Formatter.duration_verbose`` for
#: the caller and the reasoning that substitution is not a whole-message-rule
#: violation.
HOURS_AND_MINUTES = N_("%(hours)s %(minutes)s")

#: The compact hours-and-minutes duration, e.g. "1h 05m" — the journal's and
#: the Activity Log's shared shape. Source string carried over byte-for-byte
#: from the ``util`` context of ``translations/idasen_companion_es.ts`` (the
#: pre-migration home of ``gui/util.py``'s ``fmt_hm``), so its existing
#: Spanish survives the move between catalogs.
HOURS_AND_MINUTES_COMPACT = N_("%(hours)sh %(minutes)sm")

#: The compact minutes-only duration, e.g. "45m". Byte-identical to the
#: existing ``util``-context source string — see
#: :data:`HOURS_AND_MINUTES_COMPACT` above.
MINUTES_COMPACT = N_("%(minutes)sm")

#: The compact seconds-only duration, e.g. "45s". Byte-identical to the
#: existing ``util``-context source string — see
#: :data:`HOURS_AND_MINUTES_COMPACT` above.
SECONDS_COMPACT = N_("%(seconds)ss")

#: A height shown in centimetres, e.g. "110.5 cm". Source string carried
#: over byte-for-byte from the ``util`` context of
#: ``translations/idasen_companion_es.ts`` (the pre-migration home of
#: ``gui/util.py``'s ``fmt_height``), so its existing Spanish survives the
#: move between catalogs.
HEIGHT_CENTIMETRES = N_("%(value)s cm")

#: A height shown in inches, e.g. "43.50 in". Byte-identical to the
#: existing ``util``-context source string — see :data:`HEIGHT_CENTIMETRES`
#: above.
HEIGHT_INCHES = N_("%(value)s in")

#: What the automation is doing, keyed by the wire value
#: ``core/machine.py``'s ``Status`` enum carries. The long form, shown where
#: there is room for a sentence. Source strings carried over byte-for-byte
#: from the ``util`` context of ``translations/idasen_companion_es.ts`` (the
#: pre-migration home of ``gui/util.py``'s ``status_label``), so their
#: existing Spanish survives the move between catalogs.
STATUS_LABELS = {
    "active": N_("Automation active"),
    "move-failed": N_("Last move failed"),
    "unconfigured": N_("Not set up yet — no desk chosen"),
    "disabled": N_("Automation off"),
    "paused": N_("Paused"),
    "snoozed": N_("Snoozed"),
    "user-idle": N_("Waiting — you seem to be away"),
    "locked": N_("Waiting — session locked"),
    "away": N_("Waiting — switched to another session"),
    "no-session": N_("On hold — no desktop session"),
    "out-of-schedule": N_("Outside scheduled hours"),
    "held": N_("Paused — desk moved off sit/stand"),
}

#: The same states as the Overview status head shown beside the status dot.
#: Shorter than the equivalent :data:`STATUS_LABELS` wording *where the two
#: differ* — where they do not, the same source string appears in both
#: tables and is deliberately one catalog entry, not two, so a translator
#: cannot render one state two ways. Byte-identical to the existing
#: ``util``-context source strings — see :data:`STATUS_LABELS` above.
STATUS_HEADS = {
    "active": N_("Active"),
    "paused": N_("Paused"),
    "user-idle": N_("You're away"),
    "away": N_("In another session"),
    "locked": N_("Session locked"),
    "out-of-schedule": N_("Outside schedule"),
    "disabled": N_("Automation off"),
    "held": N_("Off-cycle"),
    "move-failed": N_("Last move failed"),
}

# ----- the shared cycle vocabulary (the tray and Overview say the same) -----
#
# These four were written out in both gui/tray.py and gui/pages/overview.py,
# and the duplication had already reached the catalogs: each appeared twice
# in the .ts, under the TrayIcon and OverviewPage contexts. Two entries per
# concept means a translator can render one state two ways — which is the
# drift the tray's own docstring says it copied Overview's wording to avoid.
# One entry each, here, is the fix, and it is why they are named once rather
# than quoted at a call site.

#: Stands in for the snooze deadline before the client has fetched it.
LATER = N_("later")

#: The snooze line, e.g. "Snoozed until 14:32". One whole message with the
#: time substituted in — never a verb joined to a fragment — because a
#: translator that cannot move the time relative to the words cannot
#: translate this sentence at all. The substituted value is a finished
#: clock string the caller formats; see ``core/presentation/words.py``'s
#: ``snooze_line``.
SNOOZED_UNTIL = N_("Snoozed until %s")

#: Shown where a countdown would be, once it has run out.
DUE_NOW = N_("Due now")

#: The desk is at neither preset — parked somewhere of the user's choosing.
CUSTOM = N_("Custom")

#: A running countdown as minutes and zero-padded seconds, e.g. "2:05".
#: Both halves are rendered by the locale backend and substituted in, so
#: the separator is a catalog entry rather than a Python literal. It exists
#: so a language that punctuates a countdown differently has somewhere to
#: say so; Spanish does not, and its translation matches the English for
#: the same reason :data:`DAY_RANGE` and the day/clock pattern do.
COUNTDOWN = N_("%(minutes)s:%(seconds)s")

#: The short weekday names an automation schedule is shown with, keyed by
#: the schedule's own day wire values. Source strings carried over
#: byte-for-byte from the ``util`` context of
#: ``translations/idasen_companion_es.ts`` (the pre-migration home of
#: ``gui/util.py``'s ``day_label``), so their existing Spanish survives the
#: move between catalogs.
DAY_NAMES = {
    "mon": N_("Mon"),
    "tue": N_("Tue"),
    "wed": N_("Wed"),
    "thu": N_("Thu"),
    "fri": N_("Fri"),
    "sat": N_("Sat"),
    "sun": N_("Sun"),
}

#: Stands in for the day list when an automation schedule has no days
#: selected, e.g. "Automation runs no days, 09:00–17:00." Reachable because
#: the Automation page lets every day chip be unchecked and ``_validate``
#: does not refuse an empty list.
NO_DAYS = N_("no days")

#: A run of three or more consecutive days collapsed into a range, e.g.
#: "Mon–Fri". %(first)s is the run's first day, %(last)s its last. The
#: separator is an en dash, not a hyphen.
DAY_RANGE = N_("%(first)s–%(last)s")

#: Two day-list entries joined, e.g. "Mon, Wed". Folded left across a longer
#: list to build the whole thing, e.g. "Mon, Wed, Fri" — %(first)s is
#: everything assembled so far, %(second)s the next entry. Both values are
#: substituted as complete translated messages, never assembled fragments;
#: see ``core/presentation/words.py``'s ``fmt_days`` for why one pair
#: pattern folded left is the whole key set.
DAY_PAIR = N_("%(first)s, %(second)s")

#: The desk position wire values shown as UI words, capitalised because
#: they stand alone as a label or a noun.
#:
#: These are *not* the same concept as the journal's own state words, which
#: are lowercase because they sit mid-sentence, and the two must never be
#: aliased to one entry however identical they look in English. One Spanish
#: word cannot serve both as an adjective and as the object of a
#: preposition, and a merge that assumed otherwise had to be split back
#: apart once already. The journal's set also renders through
#: ``core/presentation/english.py`` rather than through a catalog at all —
#: see ``docs/LOGGING.md``.
#:
#: Source strings carried over byte-for-byte from the ``util`` context of
#: ``translations/idasen_companion_es.ts`` (the pre-migration home of
#: ``gui/util.py``'s ``position_label``), so their existing Spanish
#: survives the move between catalogs.
POSITION_LABELS = {
    "sitting": N_("Sitting"),
    "standing": N_("Standing"),
}

#: The two protected presets, shown as UI words. A third distinct rendering
#: of the same two physical states: these are the verb-imperative form a
#: button is labelled with, where :data:`POSITION_LABELS` is what the desk
#: currently *is*. A user-created preset is the user's own words and never
#: reaches this table. Byte-identical to the existing ``util``-context
#: source strings — see :data:`POSITION_LABELS` above.
PRESET_LABELS = {
    "sit": N_("Sit"),
    "stand": N_("Stand"),
}

#: What caused a recorded transition, as stored in the stats DB's
#: ``trigger`` column and shown as a pill on the Statistics page. Lowercase
#: because the pill reads as a tag, not a sentence. Byte-identical to the
#: existing ``util``-context source strings — see :data:`POSITION_LABELS`.
TRIGGER_LABELS = {
    "automation": N_("automation"),
    "manual": N_("manual"),
    "external": N_("external"),
    "setup": N_("setup"),
}

#: The sidebar footer line while the desk is connected. Source string carried
#: over byte-for-byte from the ``util`` context of
#: ``translations/idasen_companion_es.ts`` (the pre-migration home of
#: ``gui/util.py``'s ``connection_state``), so its existing Spanish survives
#: the move between catalogs. A single altered character loses it.
CONNECTION_FOOTER_CONNECTED = N_("Desk: connected")

#: The Overview connection chip while the desk is connected. Byte-identical
#: to the existing ``util``-context source string — see
#: :data:`CONNECTION_FOOTER_CONNECTED` above.
CONNECTION_CHIP_CONNECTED = N_("Connected")

#: The sidebar footer line when the desk is unreachable, or when a persistent
#: link is configured and not up. Byte-identical to the existing
#: ``util``-context source string — see :data:`CONNECTION_FOOTER_CONNECTED`.
CONNECTION_FOOTER_DISCONNECTED = N_("Desk: disconnected")

#: The Overview connection chip for the same state. Byte-identical to the
#: existing ``util``-context source string — see
#: :data:`CONNECTION_FOOTER_CONNECTED` above.
CONNECTION_CHIP_DISCONNECTED = N_("Disconnected")

#: The sidebar footer line when the desk is reachable but only connected to
#: on demand. Byte-identical to the existing ``util``-context source string —
#: see :data:`CONNECTION_FOOTER_CONNECTED` above.
CONNECTION_FOOTER_ON_DEMAND = N_("Desk: on demand")

#: The Overview connection chip for the same state, which spells out what
#: "on demand" means where the footer has less room. Byte-identical to the
#: existing ``util``-context source string — see
#: :data:`CONNECTION_FOOTER_CONNECTED` above.
CONNECTION_CHIP_ON_DEMAND = N_("Not connected · on demand")

#: A preset tick's name next to its live height, e.g. "Sit · 110.5".
#: %(name)s is the preset's display name (already translated where it is
#: "Sit"/"Stand"; a user's own preset name is shown verbatim), %(height)s
#: the bare formatted number the rail already shows alongside it.
#: Byte-identical to the existing ``util``-context source string — see
#: :data:`HEIGHT_CENTIMETRES` above.
PRESET_TICK = N_("%(name)s · %(height)s")

