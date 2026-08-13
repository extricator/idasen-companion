"""Control of the daemon's systemd **user** unit, on the GUI's behalf.

The GUI — not the package — is what turns the daemon on. Fedora policy is
that installing a package must not enable a service, and for a *user* unit
the only mechanism available (a systemd user preset) enables it for **every
account on the machine**, which is why the packaging preset was removed. So a
fresh install ships the unit present but disabled, and something in the app
has to offer to enable it: the daemon-down banner, the setup wizard once a
desk is chosen, and the "Start automatically at login" toggle in Settings.

**Why a ``systemctl`` subprocess, against this project's D-Bus-first habit.**
systemd's own API is not usable from PySide6 here: ``Manager.EnableUnitFiles``
replies ``ba(sss)`` and ``DisableUnitFiles`` replies ``a(sss)``, and QtDBus
cannot demarshal non-variant containers — the same limitation that shapes our
own wire format (see ``gui/dbus_client.py``). Driving it over D-Bus would also
take three calls (``EnableUnitFiles`` + ``Reload`` + ``StartUnit``) to do what
``enable --now`` does in one, and would leave us reimplementing preset and
alias semantics by hand. The D-Bus-first rule is about *our* daemon's API, not
about driving systemd.

Deliberately Qt-free so the state machine below is unit-testable without an
event loop; tests monkeypatch :func:`_run`.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from ..core import journal, logmsg

UNIT = "idasen-companion.service"

#: The command a user can run by hand, quoted in error text and the README.
ENABLE_CMD = f"systemctl --user enable --now {UNIT}"
START_CMD = f"systemctl --user start {UNIT}"

# ``is-enabled`` words that mean "this starts at login". Per systemctl(1)
# table 3, *exit codes must not be used for this*: static, indirect,
# generated, transient and alias all exit 0, but only alias actually starts
# anything (the name resolves to another, enabled unit). We parse stdout.
_ENABLED_WORDS = frozenset({"enabled", "enabled-runtime", "alias"})

# States that calling ``enable`` cannot fix, mapped to why. "masked" needs an
# explicit unmask first; the rest have no [Install] section to act on, so
# there is nothing to enable. None of these should happen for our own unit —
# they're here so the UI explains itself instead of failing opaquely.
_BLOCKED_WORDS = {
    "masked": "masked",
    "masked-runtime": "masked",
    "static": "no-install",
    "generated": "no-install",
    "transient": "no-install",
    "bad": "bad",
    "not-found": "not-found",
}


@dataclass(frozen=True)
class AutostartState:
    """What ``systemctl is-enabled`` says about the daemon's unit.

    ``state`` is the raw systemd word, empty when systemd could not be
    reached at all. ``problem`` is an empty string when the toggle is usable,
    otherwise a stable key the GUI turns into localized text:
    ``unavailable`` (no systemd user manager / no ``systemctl``),
    ``not-found`` (unit not installed — a venv or Flatpak run), ``masked``,
    ``no-install``, ``bad``.
    """

    state: str
    on: bool
    problem: str

    @property
    def manageable(self) -> bool:
        """True when enabling/disabling is worth offering to the user."""
        return not self.problem

    @property
    def offer_enable(self) -> bool:
        """Whether "the daemon isn't running" is really "it never will be".

        A unit that is installed and enablable but switched off will not come
        back at the next login, so starting it for this session fixes the
        symptom and hides the cause — the banner clears, and the daemon is gone
        again tomorrow. Reached by a package remove-then-install (which
        disables the unit in every user's home), by abandoning the setup wizard
        before it offers to enable, and by a config imported from the idasen
        CLI without the wizard running at all.
        """
        return self.manageable and not self.on


def _run(args: list[str], timeout: float) -> tuple[int, str, str]:
    """Run ``systemctl --user <args>``; return (exit code, stdout, stderr).

    A missing binary or a hung systemd is reported as exit code -1 rather
    than raising, so every caller has one failure path to handle.
    """
    try:
        proc = subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return -1, "", "systemctl was not found on PATH"
    except subprocess.TimeoutExpired:
        return -1, "", "systemctl did not respond"
    except OSError as exc:  # e.g. no fork available
        return -1, "", str(exc)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def autostart_state() -> AutostartState:
    """Read whether the daemon is set to start at login.

    Cheap enough to call on every Settings page show, which is the point:
    the unit can be enabled or disabled from a terminal behind our back, so
    the toggle must re-read rather than cache.
    """
    _code, out, _err = _run(["is-enabled", UNIT], timeout=10.0)
    # ``is-enabled`` prints its verdict on stdout for every outcome it can
    # describe; empty stdout means it never got to ask (no systemd user
    # manager, no session bus, or no systemctl at all).
    if not out:
        return AutostartState("", False, "unavailable")
    # Only the last line matters: systemctl may prepend warnings, and
    # --full/aliases can add lines.
    word = out.splitlines()[-1].strip()
    if word in _ENABLED_WORDS:
        return AutostartState(word, True, "")
    problem = _BLOCKED_WORDS.get(word, "")
    # "disabled" and "indirect" are the normal off states: not enabled, but
    # an [Install] section exists, so enable will work.
    return AutostartState(word, False, problem)


def set_autostart(enable: bool) -> tuple[bool, str]:
    """Enable (and start) or disable the unit. Returns (ok, error text).

    Enabling uses ``--now`` so the daemon is working immediately rather than
    only after the next login. Disabling deliberately does **not** stop the
    running daemon: the setting is about what happens at login, and silently
    killing automation mid-session would be a bigger surprise than leaving it
    to exit at logout.
    """
    args = ["enable", "--now", UNIT] if enable else ["disable", UNIT]
    code, out, err = _run(args, timeout=20.0)
    if code == 0:
        _record_autostart(enable)
        return True, ""
    return False, err or out or "systemctl reported an unknown failure"


def _record_autostart(enable: bool) -> None:
    """Leave a trace that autostart was toggled from the GUI.

    This is a real change to system state made at a moment when the daemon —
    which owns the Activity Log — is by definition not necessarily running, so
    it used to leave no trace anywhere: ``systemctl enable`` writes "Created
    symlink" to stderr, not the journal, and after a remove/install cycle it
    was impossible to tell whether autostart had been restored from here or
    from a terminal.

    The GUI writes it to the journal itself, under the same message ids the
    daemon uses, so the Activity Log shows it in order alongside everything
    else. See docs/LOGGING.md.
    """
    message = logmsg.AUTOSTART_ENABLED if enable else logmsg.AUTOSTART_DISABLED
    journal.send(logmsg.render(message, {}, logmsg.ENGLISH_FORMATTERS),
                 message.level, channel=message.channel.value,
                 msg_id=message.id)


def start() -> tuple[bool, str]:
    """Start the unit for this session only. Returns (ok, error text).

    Used where the daemon is merely missing right now and enabling it would
    overreach — the main window's "not running" banner, and the wizard's
    first page (which needs a daemon to scan with, before the user has
    committed to anything).
    """
    code, out, err = _run(["start", UNIT], timeout=20.0)
    if code == 0:
        return True, ""
    return False, err or out or "systemctl reported an unknown failure"
