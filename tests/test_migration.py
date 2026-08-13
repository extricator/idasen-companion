import asyncio

import pytest

from idasen_companion.core.config import (
    AppConfig, ConfigError, load_config, save_config,
)
from idasen_companion.core.migration import import_idasen_cli_config

SAMPLE_YAML = """\
mac_address: E1:B2:C3:D4:E5:F6
positions:
  focus: 1.0403
  sit: 0.62
  stand: 1.1438000000000001
"""


def test_import_full_config(tmp_path):
    p = tmp_path / "idasen.yaml"
    p.write_text(SAMPLE_YAML)
    imported = import_idasen_cli_config(p)
    assert imported is not None
    assert imported.mac == "E1:B2:C3:D4:E5:F6"
    # All positions imported, including custom ones; heights rounded sanely.
    assert imported.presets == {"focus": 1.0403, "sit": 0.62, "stand": 1.1438}


def test_missing_file_returns_none(tmp_path):
    assert import_idasen_cli_config(tmp_path / "nope.yaml") is None


def test_malformed_yaml_returns_none(tmp_path):
    p = tmp_path / "idasen.yaml"
    p.write_text("just a string")
    assert import_idasen_cli_config(p) is None


def test_mac_only(tmp_path):
    p = tmp_path / "idasen.yaml"
    p.write_text("mac_address: AA:BB:CC:DD:EE:FF\n")
    imported = import_idasen_cli_config(p)
    assert imported.mac == "AA:BB:CC:DD:EE:FF"
    assert imported.presets == {}


def test_out_of_range_positions_are_skipped_not_imported(tmp_path):
    # The idasen CLI does not bound its saved positions. Importing one outside
    # our desk range made save_config reject the whole bootstrap config — and
    # since the file is written only on success, every later start repeated it.
    p = tmp_path / "idasen.yaml"
    p.write_text("mac_address: AA:BB:CC:DD:EE:FF\n"
                 "positions:\n"
                 "  sit: 0.70\n"
                 "  perch: 1.35\n"
                 "  floor: 0.10\n")
    imported = import_idasen_cli_config(p)
    assert imported.presets == {"sit": 0.70}
    assert sorted(imported.skipped) == ["floor", "perch"]


def test_a_skipped_position_does_not_block_the_bootstrap_save(tmp_path):
    # The end-to-end property that matters: whatever the CLI config holds, the
    # config we build from it must be writable.
    p = tmp_path / "idasen.yaml"
    p.write_text("mac_address: AA:BB:CC:DD:EE:FF\n"
                 "positions:\n  perch: 1.35\n  sit: 0.70\n")
    imported = import_idasen_cli_config(p)

    cfg = AppConfig()
    cfg.desk.mac = imported.mac
    cfg.presets.update(imported.presets)
    out = tmp_path / "config.toml"
    save_config(cfg, out)  # must not raise

    assert load_config(out).presets["sit"] == 0.70


def test_bootstrap_falls_back_to_defaults_when_the_import_cannot_be_saved(
        tmp_path, monkeypatch):
    """Belt and braces for the crash loop: even if something *else* makes the
    bootstrap config unwritable, the daemon must come up rather than exit 1
    before writing the file — which is what made the failure repeat forever.
    """
    from unittest.mock import MagicMock

    import idasen_companion.daemon.main as main_mod
    from idasen_companion.core.migration import ImportedSettings

    monkeypatch.setattr(main_mod, "import_idasen_cli_config",
                        lambda: ImportedSettings(mac="AA:BB:CC:DD:EE:FF",
                                                 presets={"sit": 9.0}))

    d = main_mod.Daemon.__new__(main_mod.Daemon)

    d._tasks = set()  # _spawn's strong-reference set; __init__ is bypassed here

    d._desk_lock = asyncio.Lock()  # serializes tick vs manual moves
    d.config_path = tmp_path / "config.toml"
    d.activity_log = MagicMock()

    cfg = d._load_or_bootstrap_config()  # must not raise

    assert cfg.presets["sit"] != 9.0
    assert not d.config_path.exists()
    levels = [c.args[0] for c in d.activity_log.diag.call_args_list]
    assert "error" in levels


def test_non_numeric_positions_are_ignored(tmp_path):
    p = tmp_path / "idasen.yaml"
    p.write_text("mac_address: AA:BB:CC:DD:EE:FF\n"
                 "positions:\n"
                 "  sit: 0.70\n"
                 "  bad: hello\n"
                 "  worse: true\n")   # bool is an int in Python
    imported = import_idasen_cli_config(p)
    assert imported.presets == {"sit": 0.70}
    assert imported.skipped == []  # wrong type isn't "out of range"
