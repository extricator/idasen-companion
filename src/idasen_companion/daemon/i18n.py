"""``human_delay`` stayed here on purpose when the rest of this module moved.

Its two plural literals (``"%d minute"``/``"%d minutes"``,
``"%d second"``/``"%d seconds"``) are extracted today by
``scripts/build-translations.sh``'s ``xgettext`` scan, which is scoped to this
package (``daemon/``). Widening that scope to cover ``core/`` has to land in
the same commit as the first ``core``-level translatable call — moving this
function early is harmless, but moving it *without* widening the scope opens a
window in which new strings are extracted by nothing and no gate notices.
That widening is Phase 13's CAT-05, alongside PRES-03, which merges this
function into the shared duration policy — this remainder is deliberately
temporary. See ``core/i18n.py`` for the machinery this delegates to.
"""

from __future__ import annotations

from ..core.i18n import ngettext


def human_delay(seconds: int) -> str:
    """A short, localized, correctly-pluralized delay for notifications.

    Unlike ``core.durations.format_duration_human`` (English, shared with the
    English-only journald/Activity-Log path), this renders through the
    ``gettext`` catalog so "2 minutes" / "30 seconds" translate.
    """
    if seconds >= 60:
        count = round(seconds / 60)
        return ngettext("%d minute", "%d minutes", count) % count
    count = max(1, seconds)
    return ngettext("%d second", "%d seconds", count) % count
