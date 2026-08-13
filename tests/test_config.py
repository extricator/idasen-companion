import pytest

from idasen_companion.core.config import (
    AppConfig,
    ConfigError,
    load_config,
    save_config,
)

SAMPLE = """
# my desk setup
[desk]
mac = "E1:B2:C3:D4:E5:F6"
connection = "on-demand"
linger = "20s"

[automation]
sit_duration = "50m"
stand_duration = "20m"
sit_variation = "10m"
stand_variation = "5m"
check_interval = "30s"
idle_threshold = "10m"
recent_input_threshold = "3m"
sync_interval = "5m"
interruption_policy = "leave"

[schedule]
enabled = true
days = ["mon", "wed", "fri"]
start = "08:30"
end = "18:00"

[notifications]
enabled = true
lead_time = "45s"

[presets]
sit = 0.62
stand = 1.1438
focus = 1.0403
"""


def write(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text)
    return p


def test_missing_file_yields_defaults(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.automation.sit_duration == 45 * 60
    assert cfg.automation.recent_input_threshold == 3 * 60
    assert cfg.presets == {"sit": 0.62, "stand": 1.10}
    assert cfg.desk.connection == "on-demand"


def test_load_sample(tmp_path):
    cfg = load_config(write(tmp_path, SAMPLE))
    assert cfg.desk.mac == "E1:B2:C3:D4:E5:F6"
    assert cfg.desk.linger == 20
    assert cfg.automation.sit_duration == 50 * 60
    assert cfg.automation.check_interval == 30
    assert cfg.automation.interruption_policy == "leave"
    assert cfg.schedule.enabled is True
    assert cfg.schedule.days == ["mon", "wed", "fri"]
    assert cfg.notifications.lead_time == 45
    assert cfg.presets["focus"] == 1.0403


def test_missing_sit_stand_presets_fall_back(tmp_path):
    cfg = load_config(write(tmp_path, '[presets]\nfocus = 1.04\n'))
    assert cfg.presets["sit"] == 0.62
    assert cfg.presets["stand"] == 1.10
    assert cfg.presets["focus"] == 1.04


@pytest.mark.parametrize(
    "text",
    [
        "[automation]\nsit_duration = 'banana'\n",
        "[automation]\nbogus_option = 1\n",
        "[automation]\ncheck_interval = '0s'\n",
        "[schedule]\ndays = ['funday']\n",
        "[schedule]\nstart = '25:00'\n",
        "[desk]\nconnection = 'always'\n",
        "[automation]\nexternal_move_policy = 'ignore'\n",
        "[ui]\ntray_left_click = 'wiggle'\n",
        "[ui]\ntray_middle_click = 'wiggle'\n",
        "[ui]\ntray_repeat_move = 'boomerang'\n",
        "[ui]\nclose_action = 'explode'\n",
        "[presets]\nstand = 9.0\n",
        # Wrong *types* for a preset height, not just a wrong number. These
        # went through a bare float() ahead of every guard, so they escaped as
        # ValueError/TypeError past this module's documented contract — and
        # past the daemon's `except ConfigError`, killing it mid-run on a hand
        # edit of a file the README invites you to hand-edit.
        "[presets]\nsit = 'tall'\n",
        "[presets]\nsit = 2026-01-01\n",
        "[presets]\nsit = [1, 2]\n",
        # bool is an int in Python, so this was silently accepted as 1.0 m.
        "[presets]\nsit = true\n",
        "[presets]\nsit = {a = 1}\n",  # table where a height belongs
        "[bogus_section]\nx = 1\n",
        "not toml at all [",
    ],
)
def test_invalid_configs_raise(tmp_path, text):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, text))


def test_malformed_preset_names_its_type(tmp_path):
    # The message is the whole point: it reaches the user as the daemon's
    # "invalid configuration: ..." exit line and in the GUI's Settings dialog.
    with pytest.raises(ConfigError, match=r"\[presets\] sit:.*got str"):
        load_config(write(tmp_path, "[presets]\nsit = 'tall'\n"))


def test_integer_preset_heights_are_still_accepted(tmp_path):
    # TOML distinguishes 1 from 1.0 and a hand-written config may well say
    # `sit = 1`; rejecting ints would be a regression, not a tightening.
    cfg = load_config(write(tmp_path, "[presets]\nsit = 1\n"))
    assert cfg.presets["sit"] == 1.0
    assert isinstance(cfg.presets["sit"], float)


def test_save_round_trip(tmp_path):
    path = tmp_path / "config.toml"
    cfg = AppConfig()
    cfg.desk.mac = "AA:BB:CC:DD:EE:FF"
    cfg.automation.sit_duration = 50 * 60
    cfg.presets["focus"] = 1.0403
    save_config(cfg, path)

    text = path.read_text()
    assert 'sit_duration = "50m"' in text  # durations saved as strings

    reloaded = load_config(path)
    assert reloaded.desk.mac == "AA:BB:CC:DD:EE:FF"
    assert reloaded.automation.sit_duration == 50 * 60
    assert reloaded.presets["focus"] == 1.0403


def test_external_move_policy_defaults_to_yield(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.automation.external_move_policy == "yield"


def test_automation_enabled_defaults_to_true(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.automation.enabled is True


def test_automation_enabled_round_trips(tmp_path):
    path = write(tmp_path, "[automation]\nenabled = false\n")
    cfg = load_config(path)
    assert cfg.automation.enabled is False
    save_config(cfg, path)
    assert "enabled = false" in path.read_text()
    assert load_config(path).automation.enabled is False


def test_notifications_problems_defaults_to_true(tmp_path):
    # An existing config file predates the key entirely (SAMPLE's
    # [notifications] table has only enabled/lead_time) and must still load,
    # picking up the default rather than failing the unknown-option check.
    assert load_config(tmp_path / "nope.toml").notifications.problems is True
    assert load_config(write(tmp_path, SAMPLE)).notifications.problems is True


def test_notifications_problems_round_trips(tmp_path):
    path = write(tmp_path, "[notifications]\nproblems = false\n")
    cfg = load_config(path)
    assert cfg.notifications.problems is False
    save_config(cfg, path)
    assert "problems = false" in path.read_text()
    assert load_config(path).notifications.problems is False


def test_save_writes_notifications_problems(tmp_path):
    path = tmp_path / "config.toml"
    save_config(AppConfig(), path)
    assert "problems = true" in path.read_text()


def test_interruption_policy_defaults_to_undo(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.automation.interruption_policy == "undo"


def test_invalid_interruption_policy_rejected(tmp_path):
    path = write(tmp_path, '[automation]\ninterruption_policy = "shrug"\n')
    with pytest.raises(ConfigError):
        load_config(path)


@pytest.mark.parametrize("key", ["retry_on_interruption",
                                 "return_to_start_on_interruption"])
@pytest.mark.parametrize("value,policy", [("true", "undo"), ("false", "leave")])
def test_legacy_interruption_bools_are_migrated(tmp_path, key, value, policy):
    # The 3-way interruption_policy replaced a bool that had itself been
    # renamed once. Both old spellings must still load (True = return to the
    # start height = "undo", False = "leave"), and a save must rewrite them to
    # the policy key without leaving a stale one behind.
    path = write(tmp_path, f"[automation]\n{key} = {value}\n")
    cfg = load_config(path)
    assert cfg.automation.interruption_policy == policy
    save_config(cfg, path)
    text = path.read_text()
    assert "retry_on_interruption" not in text
    assert f'interruption_policy = "{policy}"' in text


def test_explicit_interruption_policy_beats_legacy_bool(tmp_path):
    path = write(tmp_path, '[automation]\nreturn_to_start_on_interruption = true\n'
                           'interruption_policy = "retry"\n')
    assert load_config(path).automation.interruption_policy == "retry"


def test_newer_legacy_interruption_bool_wins(tmp_path):
    # A config written between the two renames carries both bools; the newer
    # spelling is the one the app was actually honouring.
    path = write(tmp_path, "[automation]\nretry_on_interruption = true\n"
                           "return_to_start_on_interruption = false\n")
    assert load_config(path).automation.interruption_policy == "leave"


def test_sync_interval_zero_round_trips(tmp_path):
    # 0 = periodic polling disabled; it must survive save/load.
    path = tmp_path / "config.toml"
    cfg = AppConfig()
    cfg.automation.sync_interval = 0
    cfg.automation.external_move_policy = "adopt"
    save_config(cfg, path)
    reloaded = load_config(path)
    assert reloaded.automation.sync_interval == 0
    assert reloaded.automation.external_move_policy == "adopt"


def test_ui_window_prefs_default(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.ui.tray_left_click == "window"
    assert cfg.ui.tray_middle_click == "toggle"
    assert cfg.ui.tray_repeat_move == "stop"
    assert cfg.ui.close_action == "tray"
    assert cfg.ui.minimize_to_tray is False
    assert cfg.ui.start_minimized is True


def test_ui_window_prefs_round_trip(tmp_path):
    path = tmp_path / "config.toml"
    cfg = AppConfig()
    cfg.ui.tray_left_click = "toggle"
    cfg.ui.tray_middle_click = "none"
    cfg.ui.tray_repeat_move = "reverse"
    cfg.ui.close_action = "quit"
    cfg.ui.minimize_to_tray = True
    cfg.ui.start_minimized = False
    save_config(cfg, path)
    reloaded = load_config(path)
    assert reloaded.ui.tray_left_click == "toggle"
    assert reloaded.ui.tray_middle_click == "none"
    assert reloaded.ui.tray_repeat_move == "reverse"
    assert reloaded.ui.close_action == "quit"
    assert reloaded.ui.minimize_to_tray is True
    assert reloaded.ui.start_minimized is False


def test_run_at_login_default(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.ui.run_at_login is False


def test_run_at_login_round_trip(tmp_path):
    path = tmp_path / "config.toml"
    cfg = AppConfig()
    cfg.ui.run_at_login = True
    save_config(cfg, path)
    reloaded = load_config(path)
    assert reloaded.ui.run_at_login is True


def test_run_at_login_absent_in_existing_config_loads_as_default(tmp_path):
    # A config file written before this option existed has no [ui]
    # run_at_login key at all -- that must load cleanly at the default,
    # never as an unknown-option error.
    path = write(tmp_path, SAMPLE + '\n[ui]\ntray_middle_click = "sit"\n')
    cfg = load_config(path)  # no ConfigError
    assert cfg.ui.run_at_login is False


def test_legacy_hotkeys_section_ignored(tmp_path):
    # The in-app global-shortcuts portal is gone, but an existing config still
    # carries its [hotkeys] table; loading must not fail the unknown-section
    # check, and saving must drop the obsolete table.
    path = write(tmp_path, SAMPLE + '\n[hotkeys]\nenabled = true\ntoggle = "CTRL+ALT+d"\n')
    cfg = load_config(path)  # no ConfigError
    assert not hasattr(cfg, "hotkeys")
    save_config(cfg, path)
    assert "[hotkeys]" not in path.read_text()
    load_config(path)  # still loads cleanly after the rewrite


def test_legacy_tray_double_click_ignored(tmp_path):
    # StatusNotifierItem trays don't deliver double-clicks, so the option was
    # removed. An existing config may still carry [ui] tray_double_click; it
    # must load (not fail the unknown-option check) and be dropped on save.
    path = write(tmp_path, SAMPLE
                 + '\n[ui]\ntray_double_click = "sit"\ntray_middle_click = "sit"\n')
    cfg = load_config(path)  # no ConfigError
    assert not hasattr(cfg.ui, "tray_double_click")
    assert cfg.ui.tray_middle_click == "sit"  # sibling key still applied
    save_config(cfg, path)
    assert "tray_double_click" not in path.read_text()
    load_config(path)


def test_legacy_sitting_height_threshold_ignored(tmp_path):
    # The sit/stand boundary is now the preset midpoint; an existing [advanced]
    # table may still carry the old key. It must load (not fail the
    # unknown-option check) and be dropped on save.
    path = write(tmp_path, SAMPLE
                 + '\n[advanced]\nsitting_height_threshold = 0.9\n'
                   'movement_tolerance = 0.03\n')
    cfg = load_config(path)  # no ConfigError
    assert not hasattr(cfg.advanced, "sitting_height_threshold")
    assert cfg.advanced.movement_tolerance == 0.03  # sibling key still applied
    save_config(cfg, path)
    assert "sitting_height_threshold" not in path.read_text()
    load_config(path)


def test_save_preserves_comments(tmp_path):
    path = write(tmp_path, SAMPLE)
    cfg = load_config(path)
    cfg.automation.sit_duration = 40 * 60
    save_config(cfg, path)
    text = path.read_text()
    assert "# my desk setup" in text
    assert 'sit_duration = "40m"' in text


def test_save_removes_deleted_presets(tmp_path):
    path = write(tmp_path, SAMPLE)
    cfg = load_config(path)
    del cfg.presets["focus"]
    save_config(cfg, path)
    assert "focus" not in path.read_text()


def test_save_rejects_invalid(tmp_path):
    cfg = AppConfig()
    cfg.presets["stand"] = 9.0
    with pytest.raises(ConfigError):
        save_config(cfg, tmp_path / "config.toml")
