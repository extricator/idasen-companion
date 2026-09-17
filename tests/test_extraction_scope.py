"""Guard: every translatable marker is actually extracted.

``scripts/build-translations.sh``'s ``xgettext`` scan covers every ``*.py``
under ``src/idasen_companion``. A marker call that the script's keyword list
doesn't recognize
would ship untranslated with nothing to notice: the ``.pot`` never grows, the
regenerate-and-diff gate stays green *because nothing changed*, and the
string ships in English forever. That is the exact failure mode a green
build hid 64 of 67 strings behind once already.

This file used to assert the narrower, ``daemon/``-only scope that predated
Phase 13's CAT-05 commit — see git history for that version. This is that
commit: the scope widened to cover ``core/`` too, and the check below is now
permanent, not a placeholder pending a later edit.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_POT_PATH = _REPO_ROOT / "po" / "idasen_companion.pot"
_SRC_ROOT = _REPO_ROOT / "src" / "idasen_companion"

_MSGID_RE = re.compile(r'^msgid "((?:[^"\\]|\\.)*)"$')
_LOCATION_RE = re.compile(r'^#:\s*(.+)$')
_PO_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')

#: Call names an extraction marker's literal is passed to, positionally --
#: gettext's own pair, and the two functions the shared layer's own register
#: (``core/presentation/register.py``) adds alongside them. Named once, as
#: data, so both checks below read the same definition rather than two that
#: could drift apart.
_MARKER_ARGS = {
    "_": (0,), "ngettext": (0, 1),
    "pgettext": (1,), "npgettext": (1, 2),
    "P_": (1,), "NP_": (1, 2),
}


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


def test_minute_plural_is_extracted_from_a_core_file():
    locations = _locations_for("%d minute")
    assert locations, "'%d minute' carries no #: source reference"
    assert all("/core/" in loc for loc in locations), locations


def test_second_plural_is_extracted_from_a_core_file():
    locations = _locations_for("%d second")
    assert locations, "'%d second' carries no #: source reference"
    assert all("/core/" in loc for loc in locations), locations


def _po_unescape(raw: str) -> str:
    return (raw.replace(r"\n", "\n")
               .replace(r"\t", "\t")
               .replace(r"\"", "\"")
               .replace(r"\\", "\\"))


def _pot_msgids() -> set[str]:
    """Every ``msgid`` and ``msgid_plural`` the committed ``.pot`` carries --
    what the last extraction run actually found, read from its output.

    A small line-oriented parser over gettext's own PO/POT grammar, handling
    the multi-line ``msgid ""`` / ``"..."`` continuation form gettext wraps
    long strings in -- the same shape ``tests/test_terminology.py``'s
    ``_iter_po_pairs`` already handles for ``po/es.po``. A naive one-line
    regex would silently miss a wrapped msgid and report it as never
    extracted, which is exactly the false alarm this check exists to avoid.
    """
    text = _POT_PATH.read_text(encoding="utf-8")
    found: set[str] = set()
    parts: list[str] = []
    section: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("msgid_plural") or line.startswith("msgid ") \
                or line.startswith("msgstr"):
            if parts:
                found.add("".join(parts))
            parts, section = [], None
            if line.startswith("msgstr"):
                continue
            section = "id"
            match = _PO_STRING_RE.search(line)
            if match:
                parts.append(_po_unescape(match.group(1)))
            continue
        if line.startswith('"') and section == "id":
            match = _PO_STRING_RE.search(line)
            if match:
                parts.append(_po_unescape(match.group(1)))
    if parts:
        found.add("".join(parts))
    return found


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _marked_literals() -> dict[str, Path]:
    """Every string literal passed positionally to a marker call, anywhere
    under ``src/idasen_companion`` except ``gui/`` -- the scope
    ``scripts/build-translations.sh`` now covers. Maps each literal to the
    file it was found in, for a readable failure; a literal appearing in
    more than one file keeps only the first, which is enough to name a
    culprit.
    """
    literals: dict[str, Path] = {}
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        if path.relative_to(_SRC_ROOT).parts[0] == "gui":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            positions = _MARKER_ARGS.get(_call_name(node))
            if positions is None:
                continue
            for position in positions:
                if position >= len(node.args):
                    continue
                arg = node.args[position]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    literals.setdefault(arg.value, path)
    return literals


def test_every_marked_literal_outside_gui_was_actually_extracted():
    """D-12's standing check: a marker call outside the GUI catalog whose
    literal ``xgettext`` did not find is invisible to the regenerate-and-diff
    gate, because there is nothing in the ``.pot`` for a translation to
    orphan. This counts what the committed ``.pot`` actually holds -- it
    never reads ``scripts/build-translations.sh``'s own invocation, so a
    keyword the script's list forgets is caught the same way a string
    outside its scope would be.
    """
    marked = _marked_literals()
    found = _pot_msgids()
    missing = {literal: str(path.relative_to(_SRC_ROOT))
               for literal, path in marked.items() if literal not in found}
    assert not missing, (
        "these marker calls are outside the GUI catalog and were not found "
        "in po/idasen_companion.pot -- run scripts/build-translations.sh "
        f"and commit the result: {missing}")
