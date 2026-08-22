"""One concept holds an entry in exactly one catalog, or the build fails.

``tests/test_translation_collisions.py`` already forbids the same *source
string* from appearing in two loci. What it cannot see is the same *concept*
in two shapes -- ``"%d min"`` beside ``"%d minutes"`` beside a bare
``" min"`` -- because each of those is a different source string and none of
them collides by that rule's own test. That was exactly the residue the six
sites D-02 rewrote: a duration or height unit word spelled out a second time
in the Qt ``.ts`` catalog, beside the shared ``core/presentation/`` layer
that already renders the same word from ``po/idasen_companion.pot``. Left
unmeasured, the property closes the day plans 15-04/15-05 land and reopens
the first time someone types a unit word into a fresh ``self.tr()``.

This module derives the protected set of unit words from
``core/presentation/register.py``'s own marked constants, read by
identifier, rather than typing the words out here a second time. Two
reasons. First, a comment explaining *why* a word is forbidden would have to
name the word, and this project has already tripped six times in one phase
over a comment quoting the literal a nearby check greps for (see
``CLAUDE.md``'s Conventions section) -- a check is exactly the kind of
"nearby sentence" that trap describes, so its own source must not spell out
what it looks for. Second, a set typed once here goes stale the moment the
register gains a tenth formatter; reading the register structurally means a
new entry is covered automatically, with no second edit.

The three flagged shapes -- a placeholder or a literal digit immediately
followed by a protected word, and a source string that is nothing but a
protected word -- are anchored deliberately narrow. A blanket substring
search over every source string would also catch a protected word used as
ordinary prose (an English preposition that happens to spell the same as a
height-unit abbreviation is exactly this catalog's one live case), which is
too broad a rule to hold together; see the "ordinary prose is not flagged"
test below, which is what keeps a future edit from widening this into that
sweep.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from idasen_companion.core.presentation import register

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TS_PATH = _REPO_ROOT / "translations" / "idasen_companion_es.ts"

# The register constants read to derive the protected set, named by
# identifier rather than by the words they carry -- see the module
# docstring. An NP_ constant is a tuple of both plural forms; an N_ constant
# is a single string. minutes_label (added by plan 15-05's caller) reaches
# MINUTES directly, so it needs no separate entry here.
_REGISTER_CONSTANT_NAMES = (
    "HOURS", "MINUTES", "SECONDS",
    "HOURS_AND_MINUTES_COMPACT", "MINUTES_COMPACT", "SECONDS_COMPACT",
    "HEIGHT_CENTIMETRES", "HEIGHT_INCHES", "SNOOZE_ACTION",
)

# A substitution placeholder immediately followed (at most one intervening
# space) by a run of letters -- that run is where a unit word sits in this
# project's own vocabulary, whether it is written out (" hour") or compacted
# onto the placeholder itself ("sh", "sm", no space at all).
_WORD_AFTER_PLACEHOLDER = re.compile(
    r"(?:%d|%s|%n|%\([A-Za-z_]+\)s) ?([A-Za-zÀ-ÿ]+)")

# The same shape, plus a literal decimal digit run standing in for a
# placeholder -- this is what a source string that bakes a specific number
# in beside the unit word looks like, rather than substituting one.
_WORD_AFTER_PLACEHOLDER_OR_DIGIT = re.compile(
    r"(?:%d|%s|%n|%\([A-Za-z_]+\)s|\d+) ?([A-Za-zÀ-ÿ]+)")


def _derive_unit_tokens() -> frozenset[str]:
    """The set of unit words the register's marked constants carry.

    Reads each name in :data:`_REGISTER_CONSTANT_NAMES` off the live
    ``register`` module -- not a literal copy of its value -- and pulls out
    the word immediately following each substitution placeholder.
    """
    tokens: set[str] = set()
    for name in _REGISTER_CONSTANT_NAMES:
        value = getattr(register, name)
        forms = value if isinstance(value, tuple) else (value,)
        for form in forms:
            tokens.update(_WORD_AFTER_PLACEHOLDER.findall(form))
    return frozenset(tokens)


#: The derived protected set. Measured against today's register, this holds
#: twelve tokens: the three duration units in full and their compact
#: one-letter forms, the two height-unit abbreviations, and the compact
#: minutes word the snooze button's own sentence bakes in.
UNIT_TOKENS = _derive_unit_tokens()

# Guard the derivation itself, at import time and unconditionally (not
# behind a bare `assert`, which `-O` strips) -- a derivation that silently
# came back empty, or smaller than the number of constants it read, would
# turn this whole module into a check that checks nothing, which is
# precisely the class of failure this milestone exists to catch elsewhere.
if not UNIT_TOKENS or len(UNIT_TOKENS) < len(_REGISTER_CONSTANT_NAMES):
    raise AssertionError(
        "the register-derived unit-token set is empty or smaller than the "
        f"{len(_REGISTER_CONSTANT_NAMES)} register constants it was read "
        f"from (got {sorted(UNIT_TOKENS)}) -- the derivation in "
        "test_catalog_concept_overlap.py is broken")


# (context, source) -> written reason a real flagged hit is not a violation.
# Keyed on the pair, not the source alone, so a future occurrence of one of
# these strings under an unrelated context is not silently covered by an
# entry that was only ever about this one site. Measured against the live
# catalog on 2026-08-22, after plans 15-04 and 15-05 landed: these five are
# the entire hit set, and every one is a real exemption rather than a
# reflex -- see the two self-check tests below, which fail if this table
# ever drifts from that measurement in either direction.
EXEMPTIONS: dict[tuple[str, str], str] = {
    ("util", " cm"): (
        "gui/util.py's suffix_height -- QAbstractSpinBox.setSuffix takes a "
        "bare string and inserts no separating space of its own (D-03, "
        "PRES-05), so the unit word has to live in the suffix string itself"),
    ("util", " in"): (
        "gui/util.py's suffix_height, same spin-box API constraint as the "
        "centimetres suffix above"),
    ("util", " min"): (
        "gui/util.py's suffix_minutes, same spin-box API constraint"),
    ("util", " s"): (
        "gui/util.py's suffix_seconds, same spin-box API constraint"),
    ("OverviewPage", "in"): (
        "the English preposition in the countdown row (\"Next: ... in "
        "...\") -- a homonym of the inches abbreviation, not a unit word; "
        "handled the way tests/test_catalog_contexts.py already handles "
        "legitimate homonyms"),
}


def _ts_context_sources(tree: ET.ElementTree):
    """Yield (context, source) for every message in a parsed ``.ts`` tree.

    Walks ``context`` -> ``name`` / ``context`` -> ``message`` -> ``source``
    directly, the same shape ``tests/test_catalog_contexts.py``'s own walk
    uses and for the same reason: this check only ever needs to know which
    context a source string sits under, not its translation.
    """
    for context in tree.getroot().findall("context"):
        name = context.find("name").text
        for message in context.findall("message"):
            source = message.find("source")
            if source is not None and source.text:
                yield name, source.text


def _flag_reason(source: str, tokens: frozenset[str] = UNIT_TOKENS) -> str | None:
    """Why ``source`` is a concept-overlap hit, or ``None`` if it is not.

    Anchored to the three shapes the interfaces block specifies: a bare
    protected word, or a protected word sitting immediately (at most one
    space) after a placeholder or a literal digit run. A protected word
    appearing anywhere else in the string -- as ordinary prose -- is not a
    hit; only the anchored shapes are.
    """
    stripped = source.strip()
    if stripped in tokens:
        return f"a bare occurrence of the protected word {stripped!r}"
    for match in _WORD_AFTER_PLACEHOLDER_OR_DIGIT.finditer(source):
        word = match.group(1)
        if word in tokens:
            return (f"{match.group(0)!r} bakes the protected word {word!r} "
                     "in beside a placeholder or a literal digit")
    return None


def _hits(tree: ET.ElementTree, exemptions: dict[tuple[str, str], str] | None = None
          ) -> dict[tuple[str, str], str]:
    """{(context, source): reason} for every unexempted concept-overlap hit."""
    exemptions = EXEMPTIONS if exemptions is None else exemptions
    found: dict[tuple[str, str], str] = {}
    for context, source in _ts_context_sources(tree):
        if (context, source) in exemptions:
            continue
        reason = _flag_reason(source)
        if reason:
            found[(context, source)] = reason
    return found


def _real_catalog_hits_unexempted() -> dict[tuple[str, str], str]:
    """Every hit the live catalog produces before any exemption is applied."""
    return _hits(ET.parse(_TS_PATH), exemptions={})


# ---- Unit tests for the derivation and the rule itself -----------------
# Synthetic in-memory catalogs, so each shape is provable regardless of
# what the shipped catalog happens to contain.

def _tree_from(xml_body: str) -> ET.ElementTree:
    return ET.ElementTree(ET.fromstring(f"<TS>{xml_body}</TS>"))


def test_the_derived_token_set_is_not_empty():
    assert UNIT_TOKENS


def test_the_derived_token_set_covers_every_register_constant_read():
    assert len(UNIT_TOKENS) >= len(_REGISTER_CONSTANT_NAMES)


def test_a_placeholder_plus_unit_string_is_flagged():
    tree = _tree_from("""
        <context><name>SomePage</name>
            <message><source>%d hour</source></message>
        </context>
    """)
    assert ("SomePage", "%d hour") in _hits(tree, exemptions={})


def test_a_literal_digit_plus_unit_string_is_flagged():
    tree = _tree_from("""
        <context><name>ScanPage</name>
            <message><source>Scanning… (about 10 s)</source></message>
        </context>
    """)
    assert ("ScanPage", "Scanning… (about 10 s)") in _hits(tree, exemptions={})


def test_a_bare_unit_string_is_flagged():
    # The expected (context, source) pair is read back off the tree itself,
    # not spelled out a second time here as a standalone literal -- one of
    # this module's own guarded tokens is a single bare word, and a second
    # literal copy of it here would be exactly the kind of untracked literal
    # the acceptance check for this module (a token appearing nowhere but
    # inside EXEMPTIONS' own keys) exists to catch.
    tree = _tree_from("""
        <context><name>util</name>
            <message><source>hour</source></message>
        </context>
    """)
    [pair] = list(_ts_context_sources(tree))
    assert pair in _hits(tree, exemptions={})


def test_a_protected_word_as_ordinary_prose_is_not_flagged():
    # The anchoring is the point: nothing here sits immediately after a
    # placeholder or a digit, so this must not be flagged even though the
    # word "hour" appears in it -- this is the test that keeps a future
    # rewrite from widening the rule into a substring sweep over prose.
    tree = _tree_from("""
        <context><name>SomePage</name>
            <message><source>The desk will move again in about an hour</source></message>
        </context>
    """)
    assert _hits(tree, exemptions={}) == {}


def test_an_exemptions_entry_is_dropped_entirely():
    tree = _tree_from("""
        <context><name>util</name>
            <message><source> cm</source></message>
        </context>
    """)
    hits = _hits(tree, exemptions={("util", " cm"): "test fixture, not a real exemption"})
    assert hits == {}


def test_an_exemption_does_not_cover_the_same_source_under_another_context():
    tree = _tree_from("""
        <context><name>util</name>
            <message><source> cm</source></message>
        </context>
        <context><name>OtherPage</name>
            <message><source> cm</source></message>
        </context>
    """)
    hits = _hits(tree, exemptions={("util", " cm"): "test fixture, not a real exemption"})
    assert ("util", " cm") not in hits
    assert ("OtherPage", " cm") in hits


# ---- Self-checks on EXEMPTIONS, in both directions ----------------------
# Mirrors test_translation_collisions.py's rules 3 and 4: a register (here,
# an exemption table) that can silently grow or silently keep a stale entry
# is an escape hatch nobody audits.

def test_no_exemption_entry_the_real_catalog_no_longer_flags():
    dead = sorted(set(EXEMPTIONS) - set(_real_catalog_hits_unexempted()))
    assert not dead, (
        "these EXEMPTIONS entries no longer describe a real concept-overlap "
        f"hit in the live catalog -- remove them: {dead}")


def test_the_exemption_table_exactly_matches_todays_real_catalog_hits():
    assert set(EXEMPTIONS) == set(_real_catalog_hits_unexempted())


# ---- Integration test against the real catalog --------------------------

def test_no_concept_holds_an_entry_in_both_catalogs():
    hits = _hits(ET.parse(_TS_PATH))
    assert not hits, (
        "these Qt catalog source strings bake in a unit word the shared "
        "core/presentation/ layer already renders from po/idasen_companion.pot "
        "-- rewrite the site as a whole message with a named slot filled by "
        "the shared duration or height formatter (ctx.fmt), so the sentence "
        "stays in the catalog its surface owns and the word does not. Do "
        f"not add an exemption for a real new site: {hits}")
