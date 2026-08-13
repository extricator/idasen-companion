"""Local statistics: per-day sit/stand seconds and transition history.

Active time is credited to the desk state it was spent in — but not per
tick. A silent window is held back until presence is settled, then flushed if
input proves the user was there, or discarded if the silence turns out to have
been an absence. See ``Daemon._tick`` and ``_flush_pending_credit``; the
``day`` parameter on ``add_active_time`` exists to serve that deferred flush.
"""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

DEFAULT_DB_PATH = Path(
    os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
) / "idasen-companion" / "stats.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily (
    day     TEXT NOT NULL,
    state   TEXT NOT NULL,
    seconds REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (day, state)
);
CREATE TABLE IF NOT EXISTS transitions (
    ts          REAL NOT NULL,
    from_state  TEXT NOT NULL,
    to_state    TEXT NOT NULL,
    trigger     TEXT NOT NULL,
    interrupted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS transitions_ts ON transitions (ts);
"""

#: Bumped whenever the schema changes, and stamped into the file via
#: ``PRAGMA user_version``. Without it a v1 file is indistinguishable from a
#: v2 one, so every future column has to be discovered by probing
#: ``PRAGMA table_info`` — and a *newer* file opened after a downgrade reads
#: as current while silently returning partial data. Free to add now, and
#: impossible to add retroactively once users have data.
SCHEMA_VERSION = 1


class _NewerSchema(Exception):
    """The file on disk was written by a build newer than this one."""

    def __init__(self, found: int):
        super().__init__(f"schema version {found}")
        self.found = found


class Stats:
    """Best-effort statistics store.

    Every operation degrades instead of raising. Statistics are a secondary
    feature and the store sits on the user's disk, so the ways it fails —
    a full or read-only ``$XDG_DATA_HOME``, a corrupt file — are ordinary. A
    write runs on *every tick*, and an exception there unwinds ``_tick`` and
    kills the control loop; systemd then restarts a daemon that survives one
    tick and dies again, so ``StartLimitBurst`` never trips and the desk
    stops moving indefinitely. Letting the numbers be wrong is strictly
    better than letting them stop the automation.

    ``on_error`` is called with a one-line English reason the first time an
    operation fails, so the failure is visible rather than merely survived.
    """

    def __init__(self, path: Path | None = None,
                 on_error: Callable[[str], None] | None = None):
        self._on_error = on_error
        self._reported = False
        self._db: sqlite3.Connection | None = None
        path = path or DEFAULT_DB_PATH
        try:
            if path != Path(":memory:"):
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            stats_connection = sqlite3.connect(str(path))
            found = stats_connection.execute("PRAGMA user_version").fetchone()[0]
            if found > SCHEMA_VERSION:
                raise _NewerSchema(found)
            stats_connection.executescript(_SCHEMA)
            # Migrations for 0 < found < SCHEMA_VERSION go here, in order. A
            # file stamped 0 is either brand new or predates this stamp; both
            # match _SCHEMA as written, so there is nothing to do for it.
            stats_connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            stats_connection.commit()
        except _NewerSchema as error:
            # Refuse rather than read it wrongly: a downgrade would otherwise
            # see a newer file as current and return partial rows.
            self._fail(
                f"the statistics database at {path} was written by a newer "
                f"version of this app (schema {error.found}, this build "
                f"understands {SCHEMA_VERSION})", error)
        except (sqlite3.Error, OSError) as error:
            self._fail(f"could not open the statistics database at {path}", error)
        else:
            self._db = stats_connection

    @property
    def available(self) -> bool:
        """Whether the store is usable. False means every call is a no-op."""
        return self._db is not None

    def _fail(self, what: str, exc: BaseException) -> None:
        """Report the first failure and swallow this one and every later one."""
        if self._reported:
            return
        self._reported = True
        if self._on_error is not None:
            self._on_error(f"{what}: {exc}")

    def close(self) -> None:
        if self._db is None:
            return
        try:
            self._db.close()
        except sqlite3.Error as error:
            self._fail("could not close the statistics database", error)

    def add_active_time(self, state: str, seconds: float, day: date | None = None) -> None:
        if self._db is None:
            return
        day_str = (day or date.today()).isoformat()
        try:
            self._db.execute(
                """INSERT INTO daily (day, state, seconds) VALUES (?, ?, ?)
                   ON CONFLICT (day, state) DO UPDATE SET seconds = seconds + excluded.seconds""",
                (day_str, state, seconds),
            )
            self._db.commit()
        except sqlite3.Error as error:
            self._fail("could not record desk time", error)

    def record_transition(self, from_state: str, to_state: str, trigger: str,
                          interrupted: bool, timestamp: float | None = None) -> None:
        if self._db is None:
            return
        try:
            self._db.execute(
                "INSERT INTO transitions (ts, from_state, to_state, trigger, interrupted)"
                " VALUES (?, ?, ?, ?, ?)",
                (timestamp if timestamp is not None else time.time(),
                 from_state, to_state, trigger, int(interrupted)),
            )
            self._db.commit()
        except sqlite3.Error as error:
            self._fail("could not record a desk transition", error)

    def daily_totals(self, start: date, end: date) -> list[tuple[str, str, float]]:
        """Rows of (day, state, seconds) between start and end inclusive."""
        if self._db is None:
            return []
        try:
            rows = self._db.execute(
                "SELECT day, state, seconds FROM daily"
                " WHERE day >= ? AND day <= ? ORDER BY day, state",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        except sqlite3.Error as error:
            self._fail("could not read daily desk totals", error)
            return []
        return [(d, s, float(sec)) for d, s, sec in rows]

    def recent_transitions(self, limit: int = 50) -> list[tuple[float, str, str, str, bool]]:
        # Clamped: the limit arrives from a D-Bus caller, and a negative one
        # becomes SQLite's "LIMIT -1", i.e. the whole table serialized to JSON.
        limit = max(1, min(int(limit), 1000))
        if self._db is None:
            return []
        try:
            rows = self._db.execute(
                "SELECT ts, from_state, to_state, trigger, interrupted FROM transitions"
                " ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        except sqlite3.Error as error:
            self._fail("could not read recent desk transitions", error)
            return []
        return [(float(ts), f, t, trig, bool(i)) for ts, f, t, trig, i in rows]
