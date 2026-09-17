"""Contextual gettext keys for deferred shared messages.

The pattern already used at ``gui/main_window.py``'s ``NAV_ITEMS``,
``gui/util.py`` and ``gui/background_portal.py``: every translatable
literal lives once, as a module-level constant marked for extraction, and
a formatter references the constant's name rather than writing a string
literal inline. This module is that register for the code under
``core/`` and for GUI constants that must wait until render time.

Every key carries a literal semantic context.  ``MessageKey`` is a ``str``
subclass, so existing formatting and English-only translators keep working;
the gettext backend additionally reads its ``context`` attribute at lookup.

**One call carries both plural forms.** :func:`NP_` takes context, singular and
the plural literal together and returns them as a pair, so
``scripts/build-translations.sh``'s ``--keyword=NP_:1c,2,3`` reads them as one
``(msgid, msgid_plural)`` entry from a single call site — unlike gettext's
own ``ngettext(singular, plural, count)``, which needs both literals again
at every *call*, this register needs them written down exactly once. This
matches Phase 12 D-02's already-committed register shape.

Do not import these markers from ``core/i18n.py`` — that module is the
process-wide gettext lookup, not a place literals are declared, and this is
not the phase to give it that second job.
"""

from __future__ import annotations


class MessageKey(str):
    """A source string plus the semantic gettext context used to look it up."""

    context: str

    def __new__(cls, context: str, source: str) -> "MessageKey":
        instance = super().__new__(cls, source)
        instance.context = context
        return instance


def P_(context: str, source: str) -> MessageKey:  # pylint: disable=invalid-name
    """Mark a contextual source string for extraction without translating it."""
    return MessageKey(context, source)


def NP_(context: str, singular: str, plural: str) -> tuple[MessageKey, MessageKey]:  # pylint: disable=invalid-name
    """Mark a contextual plural pair for extraction without translating it."""
    return MessageKey(context, singular), MessageKey(context, plural)


#: A count of whole hours. Source strings carried over byte-identically from
#: ``daemon/i18n.py``'s pre-merge literals so the extracted msgids match what
#: ``po/es.po`` already holds.
HOURS = NP_('shared.presentation', "%d hour", "%d hours")

#: A count of whole minutes. Byte-identical to the existing msgid/msgid_plural
#: in ``po/es.po`` — see the module docstring above.
MINUTES = NP_('shared.presentation', "%d minute", "%d minutes")

#: A count of whole seconds. Byte-identical to the existing msgid/msgid_plural
#: in ``po/es.po`` — see the module docstring above.
SECONDS = NP_('shared.presentation', "%d second", "%d seconds")

#: Joins two already-whole, already-translated duration messages (an hours
#: message and a minutes message) into one sentence fragment, e.g.
#: "1 hour 5 minutes". Both %(hours)s and %(minutes)s are substituted as
#: complete translated values, never assembled fragments — see
#: ``core/presentation/formatter.py``'s ``Formatter.duration_verbose`` for
#: the caller and the reasoning that substitution is not a whole-message-rule
#: violation.
HOURS_AND_MINUTES = P_('shared.presentation', "%(hours)s %(minutes)s")

#: The compact hours-and-minutes duration, e.g. "1h 05m" — the journal's and
#: the Activity Log's shared shape. Source string carried over byte-for-byte
#: from the ``util`` context of ``translations/idasen_companion_es.ts`` (the
#: pre-migration home of ``gui/util.py``'s ``fmt_hm``), so its existing
#: Spanish survives the move between catalogs.
HOURS_AND_MINUTES_COMPACT = P_('shared.presentation', "%(hours)sh %(minutes)sm")

#: The compact minutes-only duration, e.g. "45m". Byte-identical to the
#: existing ``util``-context source string — see
#: :data:`HOURS_AND_MINUTES_COMPACT` above.
MINUTES_COMPACT = P_('shared.presentation', "%(minutes)sm")

#: The picker's minutes duration, e.g. "45 min" — the unit spelled as its
#: word abbreviation with a space before it, where :data:`MINUTES_COMPACT`
#: pushes a one-letter symbol straight onto the number with no space, and
#: :data:`MINUTES` spells the word out in full. This is the shape for a
#: control the user *picks* a value from (a dropdown, a menu item, a
#: button label) — the compact form reads too terse in a control you choose
#: a value from, which is why this entry exists beside it rather than
#: replacing it.
#:
#: **Its Spanish is the same string as :data:`MINUTES_COMPACT`'s existing
#: translation, and that is accepted rather than reworded.** Measured
#: directly in ``po/es.po``: ``%(minutes)sm`` already translates to
#: ``%(minutes)s min`` — Spanish's abbreviation for "minutes" already carries
#: the space this entry's English needs, so the compact/picker split this
#: entry exists for is an English-only problem. Spanish never had it. That
#: makes the shared Spanish a translator's judgement working correctly, not a
#: near-duplicate masking a missed distinction — rewording the Spanish so the
#: two source strings' translations differ was considered and rejected,
#: because it would invent a difference the language does not have purely to
#: satisfy a check.
MINUTES_ABBREVIATED = P_('shared.presentation', "%(minutes)s min")

#: The compact seconds-only duration, e.g. "45s". Byte-identical to the
#: existing ``util``-context source string — see
#: :data:`HOURS_AND_MINUTES_COMPACT` above.
SECONDS_COMPACT = P_('shared.presentation', "%(seconds)ss")

#: A height shown in centimetres, e.g. "110.5 cm". Source string carried
#: over byte-for-byte from the ``util`` context of
#: ``translations/idasen_companion_es.ts`` (the pre-migration home of
#: ``gui/util.py``'s ``fmt_height``), so its existing Spanish survives the
#: move between catalogs.
HEIGHT_CENTIMETRES = P_('shared.presentation', "%(value)s cm")

#: A height shown in inches, e.g. "43.50 in". Byte-identical to the
#: existing ``util``-context source string — see :data:`HEIGHT_CENTIMETRES`
#: above.
HEIGHT_INCHES = P_('shared.presentation', "%(value)s in")

#: What the automation is doing, keyed by the wire value
#: ``core/machine.py``'s ``Status`` enum carries. The long form, shown where
#: there is room for a sentence. Source strings carried over byte-for-byte
#: from the ``util`` context of ``translations/idasen_companion_es.ts`` (the
#: pre-migration home of ``gui/util.py``'s ``status_label``), so their
#: existing Spanish survives the move between catalogs.
STATUS_LABELS = {
    "active": P_('shared.presentation', "Automation active"),
    "move-failed": P_('shared.presentation', "Last move failed"),
    "unconfigured": P_('shared.presentation', "Not set up yet — no desk chosen"),
    "disabled": P_('shared.presentation', "Automation off"),
    "paused": P_('shared.presentation', "Paused"),
    "snoozed": P_('shared.presentation', "Snoozed"),
    "user-idle": P_('shared.presentation', "Waiting — you seem to be away"),
    "locked": P_('shared.presentation', "Waiting — session locked"),
    "away": P_('shared.presentation', "Waiting — switched to another session"),
    "no-session": P_('shared.presentation', "On hold — no desktop session"),
    "out-of-schedule": P_('shared.presentation', "Outside scheduled hours"),
    "held": P_('shared.presentation', "Paused — desk moved off sit/stand"),
}

#: The same states as the Overview status head shown beside the status dot.
#: Shorter than the equivalent :data:`STATUS_LABELS` wording *where the two
#: differ* — where they do not, the same source string appears in both
#: tables and is deliberately one catalog entry, not two, so a translator
#: cannot render one state two ways. Byte-identical to the existing
#: ``util``-context source strings — see :data:`STATUS_LABELS` above.
STATUS_HEADS = {
    "active": P_('shared.presentation', "Active"),
    "paused": P_('shared.presentation', "Paused"),
    "user-idle": P_('shared.presentation', "You're away"),
    "away": P_('shared.presentation', "In another session"),
    "locked": P_('shared.presentation', "Session locked"),
    "out-of-schedule": P_('shared.presentation', "Outside schedule"),
    "disabled": P_('shared.presentation', "Automation off"),
    "held": P_('shared.presentation', "Off-cycle"),
    "move-failed": P_('shared.presentation', "Last move failed"),
}

# ----- the daemon's desktop notifications --------------------------------
#
# Whole sentences, not values dropped into a shape daemon/main.py assembles.
# The summaries in particular are full sentences rather than a verb joined to
# a fragment, which is what lets a translator control word order — the
# reasoning daemon/main.py's own comments carried at both sites before these
# moved here.
#
# Every source string below is carried over byte-for-byte from the literals
# daemon/main.py passed to _() until this commit, so the extracted msgids
# match what po/es.po already holds and the existing Spanish survives
# msgmerge untouched. A single altered character loses it — note the
# typographic apostrophes in "you're" and the three "didn't" strings.

#: The pre-move warning's summary when the desk is about to rise. %s is a
#: verbose delay, e.g. "1 hour 5 minutes".
PRE_MOVE_STANDING = P_('shared.presentation', "Standing up in about %s")

#: The pre-move warning's summary when the desk is about to lower.
PRE_MOVE_SITTING = P_('shared.presentation', "Sitting down in about %s")

#: The pre-move warning's body, under either summary.
PRE_MOVE_BODY = P_('shared.presentation', "The desk will move once you're due.")

#: The pre-move warning's snooze button. %d is a whole number of minutes.
SNOOZE_ACTION = P_('shared.presentation', "Snooze %d min")

#: The pre-move warning's skip button.
SKIP_ACTION = P_('shared.presentation', "Skip this one")

#: Shown when the desk is parked somewhere that is neither preset.
AUTOMATION_PAUSED_SUMMARY = P_('shared.presentation', "Automation paused")

#: The body of the same notification.
AUTOMATION_PAUSED_BODY = P_('shared.presentation', "The desk was moved to an unrecognized position. "
                            "It will resume once the desk is back at sit or "
                            "stand.")

#: The failed-move notification's summary when the desk should have risen.
MOVE_FAILED_STANDING = P_('shared.presentation', "The desk didn't stand up")

#: The failed-move notification's summary when it should have lowered.
MOVE_FAILED_SITTING = P_('shared.presentation', "The desk didn't sit down")

#: The failed-move body when the desk gave a reason. %s is that reason, in
#: the daemon's English — diagnostic detail, not translated text.
MOVE_FAILED_BODY_WITH_REASON = P_('shared.presentation', "It didn't respond (%s). The next change "
                                  "is a whole interval away.")

#: The failed-move body when no reason came back.
MOVE_FAILED_BODY = P_('shared.presentation', "It didn't respond. The next change is a whole "
                      "interval away.")

#: The failed-move notification's retry button.
TRY_NOW_ACTION = P_('shared.presentation', "Try now")


# ----- what the daemon's D-Bus error *names* mean, in the reader's language --
#
# The daemon raises DBusError with an English body, and that body crosses the
# wire — so it cannot go through the daemon's own gettext (it would be in the
# daemon's language, not the reader's) and it is in neither catalog. Keying on
# the stable error *name* and owning the sentence here is what makes these
# translatable at all. The English body is kept as diagnostic detail, not as
# the user-facing text. See core/presentation/daemon_errors.py, which is the
# only module allowed to render these, and why.

#: A translated sentence per D-Bus error name. Source strings carried over
#: byte-for-byte from the ``util`` context of
#: ``translations/idasen_companion_es.ts`` (the pre-migration home of
#: ``gui/util.py``'s ``daemon_error_message``), so their existing Spanish
#: survives the move between catalogs.
DAEMON_ERROR_MESSAGES = {
    "MoveFailed": P_('shared.presentation', "The desk did not respond. Check that it is powered and "
                     "in range, then try again."),
    "SetupFailed": P_('shared.presentation', "Could not connect to the desk. Make sure it is "
                      "powered, nearby, and in pairing mode."),
    "NoHeight": P_('shared.presentation', "Could not read the desk's height."),
    "OutOfRange": P_('shared.presentation', "That height is outside the desk's range."),
    "InvalidPreset": P_('shared.presentation', "That preset name or height is not valid."),
    "UnknownPreset": P_('shared.presentation', "There is no preset by that name."),
    "ConfigWriteFailed": P_('shared.presentation', "Could not save the configuration. Check that "
                            "your home directory is writable and has free "
                            "space."),
}

#: The last step of the error fallback chain: an error name nobody has
#: written a sentence for, arriving with no diagnostic detail either.
#: Byte-identical to the existing ``util``-context source string.
DAEMON_ERROR_GENERIC = P_('shared.presentation',
    "The background service could not carry out that request.")


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
LATER = P_('shared.presentation', "later")

#: The snooze line, e.g. "Snoozed until 14:32". One whole message with the
#: time substituted in — never a verb joined to a fragment — because a
#: translator that cannot move the time relative to the words cannot
#: translate this sentence at all. The substituted value is a finished
#: clock string the caller formats; see ``core/presentation/words.py``'s
#: ``snooze_line``.
SNOOZED_UNTIL = P_('shared.presentation', "Snoozed until %s")

#: Shown where a countdown would be, once it has run out.
DUE_NOW = P_('shared.presentation', "Due now")

#: The desk is at neither preset — parked somewhere of the user's choosing.
CUSTOM = P_('shared.presentation', "Custom")

#: A running countdown as minutes and zero-padded seconds, e.g. "2:05".
#: Both halves are rendered by the locale backend and substituted in, so
#: the separator is a catalog entry rather than a Python literal. It exists
#: so a language that punctuates a countdown differently has somewhere to
#: say so; Spanish does not, and its translation matches the English for
#: the same reason :data:`DAY_RANGE` and the day/clock pattern do.
COUNTDOWN = P_('shared.presentation', "%(minutes)s:%(seconds)s")

#: The short weekday names an automation schedule is shown with, keyed by
#: the schedule's own day wire values. Source strings carried over
#: byte-for-byte from the ``util`` context of
#: ``translations/idasen_companion_es.ts`` (the pre-migration home of
#: ``gui/util.py``'s ``day_label``), so their existing Spanish survives the
#: move between catalogs.
DAY_NAMES = {
    "mon": P_('shared.presentation', "Mon"),
    "tue": P_('shared.presentation', "Tue"),
    "wed": P_('shared.presentation', "Wed"),
    "thu": P_('shared.presentation', "Thu"),
    "fri": P_('shared.presentation', "Fri"),
    "sat": P_('shared.presentation', "Sat"),
    "sun": P_('shared.presentation', "Sun"),
}

#: Stands in for the day list when an automation schedule has no days
#: selected, e.g. "Automation runs no days, 09:00–17:00." Reachable because
#: the Automation page lets every day chip be unchecked and ``_validate``
#: does not refuse an empty list.
NO_DAYS = P_('shared.presentation', "no days")

#: A run of three or more consecutive days collapsed into a range, e.g.
#: "Mon–Fri". %(first)s is the run's first day, %(last)s its last. The
#: separator is an en dash, not a hyphen.
DAY_RANGE = P_('shared.presentation', "%(first)s–%(last)s")

#: Two day-list entries joined, e.g. "Mon, Wed". Folded left across a longer
#: list to build the whole thing, e.g. "Mon, Wed, Fri" — %(first)s is
#: everything assembled so far, %(second)s the next entry. Both values are
#: substituted as complete translated messages, never assembled fragments;
#: see ``core/presentation/words.py``'s ``fmt_days`` for why one pair
#: pattern folded left is the whole key set.
DAY_PAIR = P_('shared.presentation', "%(first)s, %(second)s")

#: A day plus a wall-clock time, e.g. "Mon 17 14:32". %(day)s and %(clock)s
#: are both finished strings the caller renders through the locale backend
#: before this pattern is applied — a language that separates a date from a
#: time differently has no other way to say so. Source string carried over
#: byte-for-byte from the ``util`` context of
#: ``translations/idasen_companion_es.ts`` (the pre-migration home of
#: ``gui/util.py``'s ``fmt_day_and_clock``), so its existing Spanish
#: survives the move between catalogs.
DAY_AND_CLOCK = P_('shared.presentation', "%(day)s %(clock)s")

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
    "sitting": P_('shared.presentation', "Sitting"),
    "standing": P_('shared.presentation', "Standing"),
}

#: The two protected presets, shown as UI words. A third distinct rendering
#: of the same two physical states: these are the verb-imperative form a
#: button is labelled with, where :data:`POSITION_LABELS` is what the desk
#: currently *is*. A user-created preset is the user's own words and never
#: reaches this table. Byte-identical to the existing ``util``-context
#: source strings — see :data:`POSITION_LABELS` above.
PRESET_LABELS = {
    "sit": P_('shared.presentation', "Sit"),
    "stand": P_('shared.presentation', "Stand"),
}

#: What caused a recorded transition, as stored in the stats DB's
#: ``trigger`` column and shown as a pill on the Statistics page. Lowercase
#: because the pill reads as a tag, not a sentence. Byte-identical to the
#: existing ``util``-context source strings — see :data:`POSITION_LABELS`.
TRIGGER_LABELS = {
    "automation": P_('shared.presentation', "automation"),
    "manual": P_('shared.presentation', "manual"),
    "external": P_('shared.presentation', "external"),
    "setup": P_('shared.presentation', "setup"),
}

#: The sidebar footer line while the desk is connected. Source string carried
#: over byte-for-byte from the ``util`` context of
#: ``translations/idasen_companion_es.ts`` (the pre-migration home of
#: ``gui/util.py``'s ``connection_state``), so its existing Spanish survives
#: the move between catalogs. A single altered character loses it.
CONNECTION_FOOTER_CONNECTED = P_('shared.presentation', "Desk: connected")

#: The Overview connection chip while the desk is connected. Byte-identical
#: to the existing ``util``-context source string — see
#: :data:`CONNECTION_FOOTER_CONNECTED` above.
CONNECTION_CHIP_CONNECTED = P_('shared.presentation', "Connected")

#: The sidebar footer line when the desk is unreachable, or when a persistent
#: link is configured and not up. Byte-identical to the existing
#: ``util``-context source string — see :data:`CONNECTION_FOOTER_CONNECTED`.
CONNECTION_FOOTER_DISCONNECTED = P_('shared.presentation', "Desk: disconnected")

#: The Overview connection chip for the same state. Byte-identical to the
#: existing ``util``-context source string — see
#: :data:`CONNECTION_FOOTER_CONNECTED` above.
CONNECTION_CHIP_DISCONNECTED = P_('shared.presentation', "Disconnected")

#: The sidebar footer line when the desk is reachable but only connected to
#: on demand. Byte-identical to the existing ``util``-context source string —
#: see :data:`CONNECTION_FOOTER_CONNECTED` above.
CONNECTION_FOOTER_ON_DEMAND = P_('shared.presentation', "Desk: on demand")

#: The Overview connection chip for the same state, which spells out what
#: "on demand" means where the footer has less room. Byte-identical to the
#: existing ``util``-context source string — see
#: :data:`CONNECTION_FOOTER_CONNECTED` above.
CONNECTION_CHIP_ON_DEMAND = P_('shared.presentation', "Not connected · on demand")

#: A preset tick's name next to its live height, e.g. "Sit · 110.5".
#: %(name)s is the preset's display name (already translated where it is
#: "Sit"/"Stand"; a user's own preset name is shown verbatim), %(height)s
#: the bare formatted number the rail already shows alongside it.
#: Byte-identical to the existing ``util``-context source string — see
#: :data:`HEIGHT_CENTIMETRES` above.
PRESET_TICK = P_('shared.presentation', "%(name)s · %(height)s")
