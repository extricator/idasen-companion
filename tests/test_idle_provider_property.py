"""Automation1.IdleProvider must be readable before the idle monitor exists.

Regression for: `_idle` is annotation-only on Daemon (`self._idle: IdleMonitor`,
never assigned), and `_setup_dbus` exports the interfaces and requests the bus
name *before* it builds the monitor. So every startup had a window where
reading the property raised AttributeError rather than falling back to
"starting" — dbus-fast caught it while emitting ObjectManager.InterfacesAdded
and dropped every other Automation1 property out of that signal along with it.
"""

from unittest.mock import MagicMock

from idasen_companion.daemon.main import Daemon


def test_reports_starting_before_the_monitor_is_built():
    # __new__, not __init__: the real startup reaches the property with the
    # attribute genuinely absent, which is what a plain `self._idle` trips on.
    d = Daemon.__new__(Daemon)
    assert d.idle_provider_name() == "starting"


def test_reports_the_provider_once_it_is_built():
    d = Daemon.__new__(Daemon)
    d._idle = MagicMock(provider_name="org.gnome.Mutter.IdleMonitor")
    assert d.idle_provider_name() == "org.gnome.Mutter.IdleMonitor"
