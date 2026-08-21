"""D-05 gives translation-key collisions an instrument, not a standing rule.

Source-as-key means one English string maps to exactly one Spanish string
project-wide: two Qt contexts, or a Qt context and the gettext catalog, that
both claim the same English source are the same translation key. Merging
roughly twenty formatters into one shared vocabulary (Phases 13-15) is the
most collision-prone moment in the whole milestone, and a collision resolved
by reflex inside a thirty-string diff is exactly the failure ``CAT-08``'s
batching requirement exists to prevent.

D-05 deliberately declines a standing rewording rule for this. Collisions
may not materialise at all, and a rule invented before any instance exists is
a rule invented without evidence -- whether they appear during Phases 13-15
is itself the evidence bearing on the deferred ID-keyed translation scheme
(see ``.planning/notes/vocabulary-and-presentation-decisions.md``). What
planning owes instead is *visibility*: this module makes every collision
candidate fail the suite the moment it appears, so it is decided deliberately
in its own commit rather than folded silently into a batch. The decision
procedure and the log of decisions already made live in
``docs/TRANSLATING.md``, in the section this module's own failure message
names.

A source string sharing more than one *locus* -- a Qt context, or the
gettext catalog as a whole -- is a collision candidate. It passes only if
``REGISTERED_SHARED_STRINGS`` below names it with a reason (window chrome
that means the same thing wherever it appears, never vocabulary crossing
catalogs), and even a registered entry still fails outright the moment its
loci disagree on the Spanish text -- that is a collision that has already
shipped, and no register entry may excuse it.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

from test_terminology import _iter_po_pairs

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TS_PATH = _REPO_ROOT / "translations" / "idasen_companion_es.ts"
_PO_PATH = _REPO_ROOT / "po" / "es.po"

# The gettext catalog is a single locus: unlike the Qt catalog it carries no
# per-string context of its own, so every msgid in po/es.po shares the one
# label below.
_GETTEXT_LOCUS = "po/es.po"

# Source string -> one-line reason sharing it is correct. Built from the
# tree as it stands: measured today, exactly these nine source strings
# appear under two or more Qt contexts, none of them disagree, and none of
# them are also in the gettext catalog. Each is window chrome that names the
# same screen or action wherever it appears, not vocabulary crossing
# catalogs -- see docs/TRANSLATING.md's collision log for how a future entry
# gets decided and added here.
REGISTERED_SHARED_STRINGS = {
    "About": "the About nav item and the About page's own title name the same screen",
    "Automation": "the Automation nav item and the Overview page's move button name the same concept",
    "Desk": "the About page's hardware name and the Overview page's move button share the app's name for the device",
    "Idasen Companion": "the app's own name, appearing in window chrome across four contexts",
    "Open window": "the tray menu entry and the settings toggle it configures name the same action",
    "Presets": "the Presets nav item and the tray's presets submenu name the same screen",
    "Quit": "the tray menu entry and the settings toggle it configures name the same action",
    "Stop": "the Overview page's cycle action and the Settings page's tray-icon-click setting name the same action",
    "Toggle sit / stand": "the tray menu entry and the settings toggle it configures name the same action",
}


def _ts_loci():
    """Yield (locus, source, translation) for every message in the .ts file.

    The locus is the Qt context name. A plural message stores its text
    across several ``<numerusform>`` children rather than directly in
    ``<translation>`` -- joined here as one comparable string, the same
    trap ``tests/test_terminology.py`` documents for the completeness check.
    """
    tree = ET.parse(_TS_PATH)
    for context in tree.getroot().findall("context"):
        locus = context.find("name").text
        for message in context.findall("message"):
            source = message.find("source")
            if source is None or not source.text:
                continue
            translation = message.find("translation")
            numerus_forms = (translation.findall("numerusform")
                              if translation is not None else [])
            if numerus_forms:
                text = "|".join((form.text or "") for form in numerus_forms)
            else:
                text = (translation.text if translation is not None else None) or ""
            yield locus, source.text, text


def _shared_source_strings():
    """{source: {locus: translation}} for every source claimed by more than
    one locus -- two or more Qt contexts, or a Qt context together with the
    gettext catalog. A source repeated within a single locus is one locus,
    not two, so it is never reported as shared by that alone.
    """
    by_source: dict[str, dict[str, str]] = {}
    for locus, source, translation in _ts_loci():
        by_source.setdefault(source, {})[locus] = translation
    for msgid, msgstr in _iter_po_pairs():
        if msgid:
            by_source.setdefault(msgid, {})[_GETTEXT_LOCUS] = msgstr
    return {source: loci for source, loci in by_source.items() if len(loci) > 1}


def test_every_shared_source_string_is_registered():
    """Rule 2: a source string claimed by more than one locus fails unless
    the register names it with a reason. A new one is a collision
    candidate -- decide it case by case (reword one side's English, accept
    the shared string, or split it another way), record the decision as its
    own commit in docs/TRANSLATING.md's collision log, and only then add its
    register entry here. See this module's docstring and D-05 in
    .planning/phases/12-the-capability-seam-the-fakes-and-the-before-picture/12-CONTEXT.md.
    """
    shared = _shared_source_strings()
    unregistered = sorted(set(shared) - set(REGISTERED_SHARED_STRINGS))
    assert not unregistered, (
        "these source strings are now claimed by more than one translation "
        "locus (a second Qt context, or both catalogs at once) and are not "
        "in REGISTERED_SHARED_STRINGS -- decide each one case by case, log "
        "the decision in docs/TRANSLATING.md's collision log in its own "
        f"commit, then register it here with the reason: {unregistered}")


def test_no_shared_source_string_has_disagreeing_translations():
    """Rule 3: unconditional, no register escape. A registered entry only
    ever excuses the *sharing* -- if the Spanish text itself disagrees
    between loci, that is a collision that has already shipped and one
    concept is rendering another's translation.
    """
    shared = _shared_source_strings()
    disagreements = {source: loci for source, loci in shared.items()
                      if len(set(loci.values())) > 1}
    assert not disagreements, (
        "these source strings are translated differently depending on "
        "where they render -- no register entry excuses this, only fixing "
        f"the disagreeing translation does: {disagreements}")


def test_the_register_holds_no_entry_that_is_no_longer_shared():
    """Rule 4: a register entry for a source string that is no longer
    shared is a dead exemption, and the register must not be allowed to
    quietly accumulate them.
    """
    shared = _shared_source_strings()
    dead = sorted(set(REGISTERED_SHARED_STRINGS) - set(shared))
    assert not dead, (
        "these REGISTERED_SHARED_STRINGS entries no longer describe a "
        f"shared source string -- remove them: {dead}")


def test_the_register_exactly_matches_todays_shared_source_strings():
    """The two directional checks above only ever report a difference in
    one direction at a time; this asserts the equality itself, so the
    register's size can never silently drift from what the catalogs
    actually share.
    """
    assert set(REGISTERED_SHARED_STRINGS) == set(_shared_source_strings())
