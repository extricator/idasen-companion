# SPDX-License-Identifier: GPL-3.0-or-later
"""Common allocation plumbing; callers supply the daemon's behavior."""

import asyncio

from idasen_companion.daemon.main import Daemon


def make_daemon_shell() -> Daemon:
    """Allocate an uninitialized daemon with its own task set and desk lock."""
    daemon = Daemon.__new__(Daemon)
    daemon._tasks = set()
    daemon._desk_lock = asyncio.Lock()
    return daemon
