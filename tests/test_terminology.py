"""One English concept gets one Spanish word, or the build fails.

On 2026-08-01, ``preset`` shipped as both "posición (guardada)" (five
``LogMessage`` entries) and "preajuste" (twenty-one other strings) in the
same session. Compounding it, "posición" was *also* the app's translation
of the desk's physical position in seven other strings -- one word covering
two concepts, and one concept split across two words. The catalogs already
enforce *completeness* (``CLAUDE.md`` forbids ``type="unfinished"`` and
empty ``msgstr``, checked both in CI and, below, inside this suite), but
nothing enforced *consistency*, so nothing caught it. A glossary alone was
considered and rejected for the same reason it failed here: it's advisory,
and advisory is exactly what failed.

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
    completeness is GATE-03's job in CI and
    test_ts_catalog_has_no_unfinished_or_empty_entry /
    test_po_catalog_has_no_empty_translation's job below, and
    double-reporting one defect as two failures makes both easier to
    ignore.
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
    # Completeness (no empty msgstr) is GATE-03's job in CI and
    # test_po_catalog_has_no_empty_translation's job below.
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


# ---- Shipped-catalog completeness -------------------------------------------
# GATE-03's CI job (.github/workflows/checks.yml) already asserts this
# property by regenerating both catalogs and grepping/msgattrib-ing the
# result -- an enforcement external to the pytest suite that also runs
# inside the RPM's %check. These two are the same property, asserted a
# second way, so it travels inside the package's own test run rather than
# living only in the workflow.


def test_ts_catalog_has_no_unfinished_or_empty_entry():
    """An incomplete catalog renders English inside a translated build, with
    nothing failing at runtime -- a missing or unconfirmed entry just falls
    back to its source text, silently. This reads
    translations/idasen_companion_es.ts (``_TS_PATH``, the same file
    ``_iter_ts_pairs`` above parses) directly, so it can also read each
    ``<translation>``'s own ``type="unfinished"`` attribute rather than only
    its text, and fails when any message is marked unfinished or carries no
    translation text at all. A plural message stores its text across
    several ``<numerusform>`` children rather than directly in
    ``<translation>``, so those are read individually -- a plain
    ``translation.text`` read is only the whitespace between them and would
    misreport every plural entry as empty. Reports every offending source
    string, not only the first, so one run tells the whole story.
    """
    tree = ET.parse(_TS_PATH)
    offenders = []
    for message in tree.getroot().iter("message"):
        source = message.find("source")
        if source is None or not source.text:
            continue
        translation = message.find("translation")
        if translation is None:
            offenders.append(source.text)
            continue
        if translation.get("type") == "unfinished":
            offenders.append(source.text)
            continue
        numerus_forms = translation.findall("numerusform")
        if numerus_forms:
            empty = not all((form.text or "").strip() for form in numerus_forms)
        else:
            empty = not (translation.text or "").strip()
        if empty:
            offenders.append(source.text)
    assert not offenders, (
        "unfinished or empty translation in "
        f"translations/idasen_companion_es.ts: {offenders}")


def test_po_catalog_has_no_empty_translation():
    """Same failure shape as above, for the daemon's gettext catalog: an
    empty ``msgstr`` renders English notifications with nothing failing at
    runtime. Iterates with ``_iter_po_pairs``, this file's own
    multi-line-aware entry reader, so a translation spread over several
    lines (``msgstr ""`` opening a continuation) is not misread as empty --
    a naive single-line check would flag exactly that shape, the case
    ``CLAUDE.md``'s own convention calls out. Skips the header entry, whose
    ``msgid`` is empty by definition.
    """
    offenders = [msgid for msgid, msgstr in _iter_po_pairs()
                 if msgid and not msgstr.strip()]
    assert not offenders, f"empty translation in po/es.po for: {offenders}"
