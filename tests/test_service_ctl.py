"""Tests for the systemd user-unit control helper.

The interesting logic is the mapping from ``systemctl is-enabled`` output to
"is the daemon set to start at login, and can the user change that here" —
which per systemctl(1) must be read from **stdout**, not the exit code. These
tests pin that down (including the states that exit 0 without being enabled),
so nobody re-introduces an exit-code check.
"""

from __future__ import annotations

import subprocess

import pytest

from idasen_companion.gui import service_ctl


@pytest.fixture
def fake_run(monkeypatch):
    """Replace the subprocess call; record args, return a canned result."""
    calls: list[list[str]] = []
    result = {"code": 0, "out": "", "err": ""}

    def _fake(args, timeout):
        calls.append(list(args))
        return result["code"], result["out"], result["err"]

    monkeypatch.setattr(service_ctl, "_run", _fake)
    return calls, result


# ----- reading state -----

@pytest.mark.parametrize("word", ["enabled", "enabled-runtime", "alias"])
def test_enabled_words_report_on(fake_run, word):
    _calls, result = fake_run
    result["out"] = word
    state = service_ctl.autostart_state()
    assert state.on is True
    assert state.manageable is True
    assert state.state == word


@pytest.mark.parametrize("word", ["disabled", "indirect"])
def test_off_but_enableable(fake_run, word):
    """The normal "off" states: the toggle must stay usable."""
    _calls, result = fake_run
    result["out"] = word
    state = service_ctl.autostart_state()
    assert state.on is False
    assert state.manageable is True
    assert state.problem == ""


@pytest.mark.parametrize("word", ["disabled", "indirect"])
def test_a_switched_off_unit_needs_enabling_not_starting(fake_run, word):
    """What the "daemon isn't running" banner offers. Starting a unit that is
    installed but switched off clears the banner and is gone again at the next
    login — the fix that looks like a fix."""
    _calls, result = fake_run
    result["out"] = word
    assert service_ctl.autostart_state().offer_enable is True


@pytest.mark.parametrize("word", ["enabled", "enabled-runtime", "alias"])
def test_an_enabled_unit_that_is_down_just_needs_starting(fake_run, word):
    _calls, result = fake_run
    result["out"] = word
    assert service_ctl.autostart_state().offer_enable is False


@pytest.mark.parametrize("word", ["masked", "static", "not-found", ""])
def test_nothing_is_offered_when_enabling_cannot_work(fake_run, word):
    """A venv run (unit not installed), a masked unit, or no systemd at all:
    offering to enable would fail, so the banner keeps its plain Start."""
    _calls, result = fake_run
    result["out"] = word
    assert service_ctl.autostart_state().offer_enable is False


@pytest.mark.parametrize("word,problem", [
    ("masked", "masked"),
    ("masked-runtime", "masked"),
    ("static", "no-install"),
    ("generated", "no-install"),
    ("transient", "no-install"),
    ("bad", "bad"),
    ("not-found", "not-found"),
])
def test_blocked_states_are_not_manageable(fake_run, word, problem):
    _calls, result = fake_run
    result["out"] = word
    state = service_ctl.autostart_state()
    assert state.on is False
    assert state.manageable is False
    assert state.problem == problem


def test_exit_code_zero_does_not_imply_enabled(fake_run):
    """systemctl exits 0 for "static" — the word, not the code, decides.

    This is the trap systemctl(1) warns about; a naive `returncode == 0`
    check would report a static unit as starting at login.
    """
    _calls, result = fake_run
    result["code"] = 0
    result["out"] = "static"
    assert service_ctl.autostart_state().on is False


def test_nonzero_exit_still_reads_the_word(fake_run):
    """"disabled" exits non-zero but is a perfectly good answer."""
    _calls, result = fake_run
    result["code"] = 1
    result["out"] = "disabled"
    state = service_ctl.autostart_state()
    assert state.state == "disabled"
    assert state.manageable is True


def test_no_output_means_systemd_unreachable(fake_run):
    _calls, result = fake_run
    result["code"] = -1
    result["out"] = ""
    result["err"] = "Failed to connect to bus"
    state = service_ctl.autostart_state()
    assert state.on is False
    assert state.problem == "unavailable"
    assert state.manageable is False


def test_unknown_word_is_treated_as_off_but_enableable(fake_run):
    """A future systemd state we don't know: don't claim it's on, and don't
    lock the user out of trying to enable it."""
    _calls, result = fake_run
    result["out"] = "some-future-state"
    state = service_ctl.autostart_state()
    assert state.on is False
    assert state.problem == ""


def test_trailing_warning_lines_are_tolerated(fake_run):
    _calls, result = fake_run
    result["out"] = "Warning: something noisy\nenabled"
    assert service_ctl.autostart_state().on is True


# ----- changing state -----

def test_enable_uses_now_so_the_daemon_runs_immediately(fake_run):
    calls, _result = fake_run
    ok, err = service_ctl.set_autostart(True)
    assert (ok, err) == (True, "")
    assert calls == [["enable", "--now", service_ctl.UNIT]]


def test_disable_does_not_stop_the_running_daemon(fake_run):
    """No --now on disable: the setting is about login, not about right now."""
    calls, _result = fake_run
    ok, _err = service_ctl.set_autostart(False)
    assert ok is True
    assert calls == [["disable", service_ctl.UNIT]]


def test_failure_surfaces_stderr(fake_run):
    _calls, result = fake_run
    result["code"] = 1
    result["err"] = "Unit is masked."
    ok, err = service_ctl.set_autostart(True)
    assert ok is False
    assert err == "Unit is masked."


def test_failure_falls_back_to_stdout_then_a_default(fake_run):
    _calls, result = fake_run
    result["code"] = 1
    result["out"] = "something on stdout"
    assert service_ctl.set_autostart(True)[1] == "something on stdout"
    result["out"] = ""
    assert service_ctl.set_autostart(True)[1]  # never an empty message


def test_start_uses_plain_start(fake_run):
    calls, _result = fake_run
    ok, _err = service_ctl.start()
    assert ok is True
    assert calls == [["start", service_ctl.UNIT]]


# ----- the subprocess wrapper itself -----

def test_missing_systemctl_is_reported_not_raised(monkeypatch):
    def boom(*_a, **_kw):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", boom)
    code, out, err = service_ctl._run(["is-enabled", "x"], timeout=1.0)
    assert code == -1
    assert out == ""
    assert "systemctl" in err


def test_hung_systemctl_is_reported_not_raised(monkeypatch):
    def boom(*_a, **_kw):
        raise subprocess.TimeoutExpired(cmd="systemctl", timeout=1.0)

    monkeypatch.setattr(subprocess, "run", boom)
    code, _out, err = service_ctl._run(["is-enabled", "x"], timeout=1.0)
    assert code == -1
    assert "respond" in err


def test_run_strips_output(monkeypatch):
    class Proc:
        returncode = 0
        stdout = "  enabled \n"
        stderr = "\n"

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_kw: Proc())
    assert service_ctl._run(["is-enabled", "x"], timeout=1.0) == (0, "enabled", "")


def test_run_targets_the_user_manager(monkeypatch):
    """Never the system manager — this is a per-user service."""
    seen = {}

    class Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def capture(args, **_kw):
        seen["args"] = args
        return Proc()

    monkeypatch.setattr(subprocess, "run", capture)
    service_ctl._run(["is-enabled", service_ctl.UNIT], timeout=1.0)
    assert seen["args"][:2] == ["systemctl", "--user"]


# ----- leaving a trace (docs/LOGGING.md) -----

@pytest.fixture
def journal_writes(monkeypatch):
    """Capture what the GUI sends to the journal."""
    sent: list[dict] = []
    monkeypatch.setattr(
        service_ctl.journal, "send",
        lambda text, level="info", **kw: sent.append(
            dict(text=text, level=level, **kw)) or True)
    return sent


@pytest.mark.parametrize("on, msg_id", [(True, "autostart.enabled"),
                                        (False, "autostart.disabled")])
def test_toggling_autostart_is_recorded_in_the_journal(fake_run, journal_writes,
                                                       on, msg_id):
    """`systemctl enable` writes "Created symlink" to stderr, not the journal,
    and the daemon that owns the Activity Log may not even be running — so
    this used to leave no trace anywhere."""
    service_ctl.set_autostart(on)
    assert [w["msg_id"] for w in journal_writes] == [msg_id]
    assert journal_writes[0]["channel"] == "activity"
    assert journal_writes[0]["text"]


def test_a_failed_toggle_is_not_recorded(fake_run, journal_writes):
    """Nothing changed, so nothing to report — rule 2."""
    _calls, result = fake_run
    result["code"] = 1
    service_ctl.set_autostart(True)
    assert journal_writes == []
