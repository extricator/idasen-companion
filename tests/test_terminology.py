"""One English concept gets one Spanish word, or the build fails.

On 2026-08-01, ``preset`` shipped as both "posición (guardada)" (five
``LogMessage`` entries) and "preajuste" (twenty-one other strings) in the
same session. Compounding it, "posición" was *also* the app's translation
of the desk's physical position in seven other strings -- one word covering
two concepts, and one concept split across two words. The catalogs already
enforce *completeness* (``CLAUDE.md`` forbids ``type="unfinished"`` and
empty ``msgstr``), but nothing enforced *consistency*, so nothing caught
it. A glossary alone was considered and rejected for the same reason it
failed here: it's advisory, and advisory is exactly what failed.

This is the enforcement instead: a term list plus a test, shaped like
``tests/test_log_catalog.py`` (the only reason catalog drift is caught
today). ``docs/TRANSLATING.md`` points a translator at ``TERMS`` below
rather than keeping a second copy that could drift from it.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TS_PATH = _REPO_ROOT / "translations" / "idasen_companion_es.ts"
_PO_PATH = _REPO_ROOT / "po" / "es.po"

# English term -> {language code: required stem in the translation}.
# Adding a language means adding a key to the inner dict, not editing any
# test below. Stems, not whole words, because Spanish participles agree
# with gender (guardado/guardada) -- "preajust" covers preajuste and
# preajustes, "posici" covers posición and posiciones.
TERMS = {
    "preset": {"es": "preajust"},
    "position": {"es": "posici"},
}

# Source strings where the English term legitimately doesn't name a
# glossary concept: {source string: written reason}. Ships empty on
# purpose -- the measured false-positive rate against the current
# catalogs is 0 across 36 matching strings (35 in the .ts, 1 in the
# .po), and an escape hatch added before it's needed is one nobody
# audits. Add an entry here only once a real false positive is found,
# with the reason as the value.
EXCEPTIONS = {}


def _find_violation(source, translation, lang, exceptions=EXCEPTIONS):
    """Return the English term the pair fails on, or ``None``.

    Case-insensitive on both sides. The English term is matched as a
    substring of the source (so "presets" satisfies "preset"), and the
    language's stem is matched as a substring of the translation (so
    "preajuste"/"preajustes" both satisfy "preajust" without hard-coding
    every inflected form). An empty translation is never reported --
    completeness is GATE-03's job elsewhere, and double-reporting one
    defect as two failures makes both easier to ignore.
    """
    if not translation:
        return None
    if source in exceptions:
        return None
    lower_source = source.lower()
    lower_translation = translation.lower()
    for term, stems in TERMS.items():
        stem = stems.get(lang)
        if stem is None or term not in lower_source:
            continue
        if stem not in lower_translation:
            return term
    return None


def _iter_ts_pairs():
    """Yield (source, translation) for every message in the .ts file."""
    tree = ET.parse(_TS_PATH)
    for message in tree.getroot().iter("message"):
        source = message.find("source")
        if source is None or not source.text:
            continue
        translation = message.find("translation")
        text = translation.text if translation is not None else None
        yield source.text, text or ""


_PO_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _po_unescape(raw):
    return (raw.replace(r"\n", "\n")
               .replace(r"\t", "\t")
               .replace(r"\"", "\"")
               .replace(r"\\", "\\"))


def _iter_po_pairs():
    """Yield (msgid, msgstr) for every entry in po/es.po.

    A small regex parser over gettext's own PO grammar -- stdlib only, no
    new dependency. Handles the multi-line ``msgid ""`` / ``"..."``
    continuation form gettext wraps long strings in (the same shape that
    makes a naive ``grep '^msgstr ""$'`` false-positive, per
    ``tests/test_packaging.py``'s neighbours in GATE-03). Plural
    ``msgstr[N]`` forms are concatenated together: for terminology
    purposes we only need to know whether the stem appears anywhere in
    the translation, not which plural form it's in.
    """
    text = _PO_PATH.read_text(encoding="utf-8")
    entries = []
    msgid_parts = []
    msgstr_parts = []
    section = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("msgid_plural"):
            section = "id"
            match = _PO_STRING_RE.search(line)
            if match:
                msgid_parts.append(_po_unescape(match.group(1)))
            continue
        if line.startswith("msgid "):
            if msgid_parts or msgstr_parts:
                entries.append(("".join(msgid_parts), "".join(msgstr_parts)))
            msgid_parts, msgstr_parts, section = [], [], "id"
            match = _PO_STRING_RE.search(line)
            if match:
                msgid_parts.append(_po_unescape(match.group(1)))
            continue
        if line.startswith("msgstr"):
            section = "str"
            match = _PO_STRING_RE.search(line)
            if match:
                msgstr_parts.append(_po_unescape(match.group(1)))
            continue
        if line.startswith('"'):
            match = _PO_STRING_RE.search(line)
            if not match:
                continue
            value = _po_unescape(match.group(1))
            if section == "id":
                msgid_parts.append(value)
            elif section == "str":
                msgstr_parts.append(value)
            continue
    if msgid_parts or msgstr_parts:
        entries.append(("".join(msgid_parts), "".join(msgstr_parts)))
    return entries


# ---- Unit tests for the matching rule itself -------------------------------
# Synthetic pairs, so each rule is provable on its own rather than only
# hoping the real catalogs happen to exercise it.

def test_a_mistranslated_preset_fails():
    assert _find_violation(
        "Save this preset", "Guardar esta posición", "es") == "preset"


def test_a_correctly_translated_preset_passes():
    assert _find_violation(
        "Save this preset", "Guardar este preajuste", "es") is None


def test_a_mistranslated_position_fails():
    assert _find_violation(
        "Return to the last position", "Volver al último sitio", "es"
    ) == "position"


def test_a_correctly_translated_position_passes():
    assert _find_violation(
        "Return to the last position", "Volver a la última posición", "es"
    ) is None


def test_the_plural_preajustes_satisfies_the_preajust_stem():
    assert _find_violation(
        "Manage your presets", "Administra tus preajustes", "es") is None


def test_an_empty_translation_is_not_reported():
    # Completeness (no empty msgstr) is GATE-03's job, checked elsewhere.
    assert _find_violation("Save this preset", "", "es") is None


def test_matching_is_case_insensitive_on_both_sides():
    assert _find_violation(
        "SAVE THIS PRESET", "GUARDAR ESTE PREAJUSTE", "es") is None
    assert _find_violation(
        "SAVE THIS PRESET", "GUARDAR ESTA POSICIÓN", "es") == "preset"


def test_an_exceptions_table_entry_is_skipped():
    exceptions = {"Save this preset": "test fixture, not a real exception"}
    assert _find_violation(
        "Save this preset", "Guardar esta posición", "es",
        exceptions=exceptions) is None


def test_the_exceptions_table_ships_empty():
    """Seeded empty on purpose (0 false positives measured across 36
    matching strings in the current catalogs). An entry added before a
    real false positive is found is an escape hatch nobody audits --
    if you're adding one, write the reason as its value."""
    assert EXCEPTIONS == {}


# ---- Integration tests against the real catalogs ---------------------------

def test_ts_terminology_is_consistent():
    violations = [(source, term)
                  for source, translation in _iter_ts_pairs()
                  for term in [_find_violation(source, translation, "es")]
                  if term]
    assert not violations, (
        "terminology drift in translations/idasen_companion_es.ts "
        f"(source, English term that lacks its mapped Spanish stem): "
        f"{violations}")


def test_po_terminology_is_consistent():
    violations = [(source, term)
                  for source, translation in _iter_po_pairs()
                  for term in [_find_violation(source, translation, "es")]
                  if term]
    assert not violations, (
        "terminology drift in po/es.po "
        f"(source, English term that lacks its mapped Spanish stem): "
        f"{violations}")


@pytest.mark.parametrize("term", sorted(TERMS))
def test_every_term_has_at_least_one_language(term):
    assert TERMS[term], f"{term!r} maps to no language at all"
