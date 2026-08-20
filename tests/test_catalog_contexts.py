"""One concept gets one catalog entry, or the build fails.

Eight concepts each reached the Qt catalog twice: a page kept its own
``self.tr(...)`` copy of a word the shared vocabulary in ``gui/util.py``
already named. Commit ``cd9a2c2`` consolidated four earlier doubled
strings (``later``, ``Snoozed until %s``, ``Due now``, ``Custom``) and
states the rule this test enforces: copying wording between two call
sites is not a mechanism for keeping them in sync, one catalog entry is.

The rule is scoped to the ``util`` context specifically, not to
duplicates in general. Nine English words legitimately appear more than
once in the catalog because unrelated pages describe unrelated things in
the same spelling (``Desk`` the About page's hardware name beside
``Desk`` the Overview page's move button; ``Stop`` a cycle action beside
``Stop`` a snooze action). Commit ``f3c2add`` records a merge that was
*wrong* for exactly this reason: two of those homonyms were folded into
one Spanish word and had to be split back apart. A blanket
no-duplicates rule would refight that merge. Pairing every duplicate
against ``util`` specifically catches only the eight concepts whose
second copy is redundant with the shared vocabulary, and leaves the
nine homonyms alone.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TS_PATH = _REPO_ROOT / "translations" / "idasen_companion_es.ts"

# Source strings the util-pairing rule may not fire on: {source string:
# written reason}. Ships empty on purpose -- measured against the current
# catalog on 2026-08-20, the eight target concepts were the entire overlap
# between the util context and any other, and after this phase's merges
# that set is empty. An exemption added before a real false positive is
# found is an escape hatch nobody audits. Add an entry here only once a
# real false positive is found, with the reason as the value.
EXCEPTIONS = {}


def _source_contexts(tree, exceptions=EXCEPTIONS):
    """{source string: {context names it appears under}}, exceptions dropped.

    Walks ``context`` -> ``name`` and ``context`` -> ``message`` -> ``source``
    directly, rather than flattening every ``<message>`` in the tree the way
    ``test_terminology.py``'s catalog-pair walk does -- that walk only ever
    needs (source, translation) pairs and is blind to which context a
    message is under, which is the one thing this test needs to know.
    """
    by_source: dict[str, set[str]] = {}
    for context in tree.getroot().findall("context"):
        name = context.find("name").text
        for message in context.findall("message"):
            source = message.find("source")
            if source is not None and source.text and source.text not in exceptions:
                by_source.setdefault(source.text, set()).add(name)
    return by_source


def _util_overlaps(by_source):
    """{source string: context set} for every string that is both in
    ``util`` and at least one other context -- the violation this test
    exists to catch."""
    return {source: contexts for source, contexts in by_source.items()
            if "util" in contexts and len(contexts) > 1}


# ---- Unit tests for the rule itself -----------------------------------
# Synthetic in-memory catalogs, so the rule is provable without depending
# on the real one happening to exercise every case.

def _tree_from(xml_body):
    return ET.ElementTree(ET.fromstring(
        f"<TS>{xml_body}</TS>"))


def test_a_string_shared_between_util_and_another_context_is_an_overlap():
    tree = _tree_from("""
        <context><name>util</name>
            <message><source>Sit</source></message>
        </context>
        <context><name>OverviewPage</name>
            <message><source>Sit</source></message>
        </context>
    """)
    overlaps = _util_overlaps(_source_contexts(tree))
    assert overlaps == {"Sit": {"util", "OverviewPage"}}


def test_a_string_shared_between_two_non_util_contexts_is_not_an_overlap():
    # The homonym case: two unrelated pages use the same English spelling
    # for different things, and neither copy is in util at all.
    tree = _tree_from("""
        <context><name>AboutPage</name>
            <message><source>Desk</source></message>
        </context>
        <context><name>OverviewPage</name>
            <message><source>Desk</source></message>
        </context>
    """)
    assert _util_overlaps(_source_contexts(tree)) == {}


def test_a_string_only_in_util_is_not_an_overlap():
    tree = _tree_from("""
        <context><name>util</name>
            <message><source>Paused</source></message>
        </context>
    """)
    assert _util_overlaps(_source_contexts(tree)) == {}


def test_the_same_source_repeated_within_one_context_is_not_an_overlap():
    tree = _tree_from("""
        <context><name>util</name>
            <message><source>Paused</source></message>
            <message><source>Paused</source></message>
        </context>
    """)
    by_source = _source_contexts(tree)
    assert by_source["Paused"] == {"util"}
    assert _util_overlaps(by_source) == {}


def test_an_exceptions_table_entry_is_dropped_entirely():
    tree = _tree_from("""
        <context><name>util</name>
            <message><source>Sit</source></message>
        </context>
        <context><name>OverviewPage</name>
            <message><source>Sit</source></message>
        </context>
    """)
    by_source = _source_contexts(tree, exceptions={"Sit": "test fixture, not a real exception"})
    assert "Sit" not in by_source


def test_the_exceptions_table_ships_empty():
    """Seeded empty on purpose -- measured 2026-08-20, the eight target
    concepts were the entire util overlap, and after this phase's merges
    the set is empty. An entry added before a real false positive is
    found is an escape hatch nobody audits -- if you're adding one,
    write the reason as its value."""
    assert EXCEPTIONS == {}


# ---- Integration tests against the real catalog ------------------------

def test_no_source_string_is_shared_between_util_and_another_context():
    tree = ET.parse(_TS_PATH)
    overlaps = _util_overlaps(_source_contexts(tree))
    assert not overlaps, (
        "these source strings appear in the util context and at least one "
        "other -- point the other context's call site at the shared "
        "accessor in gui/util.py instead of keeping a local self.tr() "
        f"copy: {overlaps}")


def test_the_nine_legitimate_homonyms_still_span_multiple_contexts():
    # Not a duplicate count and not a context count (D-14) -- Idasen
    # Companion legitimately sits under four contexts, not two, so this
    # only asserts "at least 2", which every homonym satisfies by
    # definition and no correct merge could ever violate.
    homonyms = [
        "About", "Automation", "Desk", "Idasen Companion", "Open window",
        "Presets", "Quit", "Stop", "Toggle sit / stand",
    ]
    tree = ET.parse(_TS_PATH)
    by_source = _source_contexts(tree)
    missing = [word for word in homonyms if word not in by_source]
    assert not missing, f"expected homonyms missing from the catalog: {missing}"
    too_few = {word: by_source[word] for word in homonyms
               if len(by_source[word]) < 2}
    assert not too_few, (
        "these words were expected to legitimately span multiple contexts "
        f"but no longer do: {too_few}")
