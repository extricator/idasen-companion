"""Guard: the plural notification strings stay extracted from ``daemon/``.

``scripts/build-translations.sh``'s ``xgettext`` scan is scoped to
``daemon/*.py`` (see that script and ``core/i18n.py``'s docstring). As long
as ``human_delay``'s two plural literals live in a file under ``daemon/``,
the committed ``po/idasen_companion.pot`` carries both entries with a
``#:`` location comment naming a ``daemon/`` file. If the literals (or the
function around them) ever move under ``core/`` without the scan widening
in the same commit — the exact mistake RESEARCH.md's Pitfall 1 describes —
regenerating the catalog silently drops both entries, and this is the test
that would fail instead of a green, silently-incomplete build.

**Deliberately temporary.** Phase 13's PRES-03 merges ``human_delay`` into
the shared duration policy, and CAT-05 widens the extraction scope to cover
``core/`` in that same commit. At that point this assertion is edited on
purpose, not deleted in passing — the plural strings will legitimately be
extracted from a ``core/``-scoped scan.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_POT_PATH = _REPO_ROOT / "po" / "idasen_companion.pot"

_MSGID_RE = re.compile(r'^msgid "((?:[^"\\]|\\.)*)"$')
_LOCATION_RE = re.compile(r'^#:\s*(.+)$')


def _iter_pot_entries():
    """Yield ``(msgid, locations)`` for every entry in the ``.pot`` file.

    ``locations`` is the list of ``#:`` source-reference paths recorded for
    that entry (``--add-location=file``, so one bare path per reference, no
    line number).
    """
    text = _POT_PATH.read_text(encoding="utf-8")
    entries = []
    locations: list[str] = []
    for raw_line in text.splitlines():
        location_match = _LOCATION_RE.match(raw_line)
        if location_match:
            locations.append(location_match.group(1).strip())
            continue
        msgid_match = _MSGID_RE.match(raw_line)
        if msgid_match:
            entries.append((msgid_match.group(1), locations))
            locations = []
    return entries


def _locations_for(msgid: str) -> list[str]:
    for entry_id, locations in _iter_pot_entries():
        if entry_id == msgid:
            return locations
    raise AssertionError(f"{msgid!r} not found in {_POT_PATH}")


def test_pot_file_exists():
    assert _POT_PATH.is_file()


def test_minute_plural_is_extracted_from_a_daemon_file():
    locations = _locations_for("%d minute")
    assert locations, "'%d minute' carries no #: source reference"
    assert all("/daemon/" in loc for loc in locations), locations


def test_second_plural_is_extracted_from_a_daemon_file():
    locations = _locations_for("%d second")
    assert locations, "'%d second' carries no #: source reference"
    assert all("/daemon/" in loc for loc in locations), locations
