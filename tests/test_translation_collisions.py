"""Migration evidence for the frozen Qt catalog and unified gettext catalog.

The old cross-catalog collision registry became meaningless once gettext
owned every app message.  Until Phase 7 removes the frozen Qt artifacts, this
file instead proves the migration source remains intact and every live entry
has an explicit semantic context with compatible placeholders.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from babel.messages import pofile


ROOT = Path(__file__).resolve().parent.parent
TS_PATH = ROOT / "translations/idasen_companion_es.ts"
PO_PATH = ROOT / "po/es.po"
PLACEHOLDER = re.compile(r"%(?:\([^)]+\))?[#0 +\-]?(?:\d+)?(?:\.\d+)?[a-zA-Z]")


def _catalog():
    with PO_PATH.open("rb") as handle:
        return pofile.read_po(handle, locale="es")


def test_frozen_qt_catalog_retains_the_phase_one_migration_baseline():
    messages = list(ET.parse(TS_PATH).getroot().iter("message"))
    assert len(messages) == 322
    assert all((translation := message.find("translation")) is not None
               and translation.get("type") != "unfinished"
               for message in messages)


def test_every_live_gettext_message_has_a_semantic_context():
    missing = [message.id for message in _catalog()
               if message.id and not message.context]
    assert not missing


def test_context_and_source_pairs_are_unique():
    keys = [(message.context, message.id) for message in _catalog() if message.id]
    assert len(keys) == len(set(keys))


def test_source_and_spanish_placeholders_match():
    mismatches = []
    for message in _catalog():
        if not message.id:
            continue
        sources = message.id if isinstance(message.id, tuple) else (message.id,)
        strings = (message.string if isinstance(message.string, tuple)
                   else (message.string,))
        source_slots = [sorted(PLACEHOLDER.findall(source.replace("%%", "")))
                        for source in sources]
        translated_slots = [sorted(PLACEHOLDER.findall(value.replace("%%", "")))
                            for value in strings]
        if len(source_slots) == 1:
            source_slots *= len(translated_slots)
        if source_slots != translated_slots:
            mismatches.append((message.context, message.id, message.string))
    assert not mismatches
