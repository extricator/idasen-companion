"""Import settings from the idasen CLI's config (~/.config/idasen/idasen.yaml).

Imports the desk MAC address and *all* saved positions (not just
sit/stand — custom presets like "focus" come along too).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .config import MAX_HEIGHT, MIN_HEIGHT

IDASEN_CLI_CONFIG = Path(
    os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
) / "idasen" / "idasen.yaml"


@dataclass
class ImportedSettings:
    mac: str = ""
    presets: dict[str, float] = field(default_factory=dict)
    #: Names dropped because their height is outside the desk's range. The
    #: caller reports these; they are not an error, and importing them would
    #: be (see below).
    skipped: list[str] = field(default_factory=list)


def import_idasen_cli_config(path: Path | None = None) -> ImportedSettings | None:
    """Read the idasen CLI config. Returns None if absent or unreadable."""
    import yaml

    path = path or IDASEN_CLI_CONFIG
    try:
        data = yaml.safe_load(path.read_text())
    except (FileNotFoundError, OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None

    imported = ImportedSettings()
    mac = data.get("mac_address")
    if isinstance(mac, str):
        imported.mac = mac

    positions = data.get("positions")
    if isinstance(positions, dict):
        for name, height in positions.items():
            if not isinstance(name, str):
                continue
            if isinstance(height, bool) or not isinstance(height, (int, float)):
                continue
            # Range-check here rather than leaving it to save_config. The idasen
            # CLI does not bound its saved positions, so a config carrying one
            # outside our desk range made the *first* start fail validation —
            # and because the file is written only after save_config succeeds,
            # every subsequent start repeated it. With Restart=on-failure that
            # is a crash loop the user cannot see the cause of, on the one path
            # every idasen-CLI user takes.
            if MIN_HEIGHT - 0.01 <= float(height) <= MAX_HEIGHT + 0.01:
                imported.presets[name] = round(float(height), 4)
            else:
                imported.skipped.append(name)

    if not imported.mac and not imported.presets:
        return None
    return imported
