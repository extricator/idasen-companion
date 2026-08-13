"""BlueZ helpers: find desks the computer already knows about.

If the user paired the desk through their desktop's Bluetooth settings
(the most likely prior action for a non-CLI user), it sits in BlueZ's
device registry even when not advertising. Offering those devices makes
first-run setup a single confirmation instead of a scan.
"""

from __future__ import annotations

import re

_DESK_NAME_RE = re.compile(r"^desk\b|linak", re.IGNORECASE)


def _unwrap(value):
    """dbus-fast wraps property values in Variant; unwrap defensively."""
    return getattr(value, "value", value)


def looks_like_desk(name: str) -> bool:
    return bool(_DESK_NAME_RE.search(name.strip()))


def parse_paired_desks(managed_objects: dict) -> list[tuple[str, str]]:
    """Extract (name, mac) of paired desk-looking devices from a BlueZ
    ObjectManager.GetManagedObjects result."""
    found = []
    for interfaces in managed_objects.values():
        device = interfaces.get("org.bluez.Device1")
        if not device:
            continue
        name = _unwrap(device.get("Name")) or _unwrap(device.get("Alias")) or ""
        address = _unwrap(device.get("Address")) or ""
        paired = bool(_unwrap(device.get("Paired")))
        if address and paired and looks_like_desk(name):
            found.append((name, address))
    return sorted(found)


def merge_devices(known: list[tuple[str, str]],
                  scanned: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Combine paired (preferred, listed first) and freshly scanned
    devices, deduplicated by MAC."""
    seen = set()
    merged = []
    for name, mac in list(known) + list(scanned):
        key = mac.upper()
        if key in seen:
            continue
        seen.add(key)
        merged.append((name, mac))
    return merged
