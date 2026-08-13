import sqlite3
from datetime import date
from pathlib import Path

import pytest

from idasen_companion.daemon.stats import Stats


def make_stats():
    return Stats(Path(":memory:"))


def test_active_time_accumulates_per_day_and_state():
    s = make_stats()
    day = date(2026, 7, 17)
    s.add_active_time("sitting", 60, day)
    s.add_active_time("sitting", 30, day)
    s.add_active_time("standing", 45, day)
    rows = s.daily_totals(day, day)
    assert ("2026-07-17", "sitting", 90.0) in rows
    assert ("2026-07-17", "standing", 45.0) in rows


def test_daily_totals_range_filter():
    s = make_stats()
    s.add_active_time("sitting", 10, date(2026, 7, 1))
    s.add_active_time("sitting", 20, date(2026, 7, 15))
    s.add_active_time("sitting", 30, date(2026, 8, 1))
    rows = s.daily_totals(date(2026, 7, 1), date(2026, 7, 31))
    assert [r[2] for r in rows] == [10.0, 20.0]


def test_transitions_recorded_most_recent_first():
    s = make_stats()
    s.record_transition("sitting", "standing", "automation", False, timestamp=100.0)
    s.record_transition("standing", "sitting", "manual", True, timestamp=200.0)
    rows = s.recent_transitions(10)
    assert rows[0] == (200.0, "standing", "sitting", "manual", True)
    assert rows[1] == (100.0, "sitting", "standing", "automation", False)


def test_transitions_limit():
    s = make_stats()
    for i in range(20):
        s.record_transition("sitting", "standing", "automation", False, timestamp=float(i))
    assert len(s.recent_transitions(5)) == 5


def test_transitions_limit_is_clamped():
    # The limit arrives from a D-Bus caller. A negative one becomes SQLite's
    # "LIMIT -1" — the entire table serialized to JSON onto the bus.
    s = make_stats()
    for i in range(20):
        s.record_transition("sitting", "standing", "automation", False, timestamp=float(i))
    assert len(s.recent_transitions(-1)) == 1
    assert len(s.recent_transitions(0)) == 1
    assert len(s.recent_transitions(10_000)) == 20


# ----- the on-disk store (every other test here is :memory:) -----

def test_rows_survive_close_and_reopen(tmp_path):
    # The schema had only ever run against a fresh :memory: database, so a
    # future edit that isn't re-run-safe would pass the whole suite and fail
    # on every existing user's file.
    path = tmp_path / "sub" / "stats.sqlite"
    day = date(2026, 7, 17)

    s = Stats(path)
    assert path.exists()  # parent directory created
    s.add_active_time("sitting", 90, day)
    s.record_transition("sitting", "standing", "automation", False, timestamp=100.0)
    s.close()

    reopened = Stats(path)
    assert reopened.available
    assert ("2026-07-17", "sitting", 90.0) in reopened.daily_totals(day, day)
    assert reopened.recent_transitions(10)[0][0] == 100.0
    reopened.add_active_time("sitting", 10, day)
    assert ("2026-07-17", "sitting", 100.0) in reopened.daily_totals(day, day)


# ----- degradation: a stats failure must never stop the desk moving -----

def test_a_corrupt_database_is_reported_and_disabled(tmp_path):
    path = tmp_path / "stats.sqlite"
    path.write_bytes(b"this is not a database, not even slightly")
    errors = []

    s = Stats(path, on_error=errors.append)

    assert not s.available
    assert len(errors) == 1
    # ...and every operation is a no-op rather than a raise.
    s.add_active_time("sitting", 60)
    s.record_transition("sitting", "standing", "automation", False)
    assert s.daily_totals(date(2026, 7, 1), date(2026, 7, 2)) == []
    assert s.recent_transitions(10) == []
    s.close()
    assert len(errors) == 1  # reported once, not once per call


def test_a_write_failure_is_reported_once_and_swallowed(tmp_path):
    path = tmp_path / "stats.sqlite"
    errors = []
    s = Stats(path, on_error=errors.append)

    s._db.close()  # every later statement now raises ProgrammingError
    with pytest.raises(sqlite3.Error):
        s._db.execute("SELECT 1")  # the failure is real, not simulated

    s.add_active_time("sitting", 60)
    s.add_active_time("standing", 60)
    s.record_transition("sitting", "standing", "automation", False)
    assert s.daily_totals(date(2026, 7, 1), date(2026, 7, 2)) == []

    assert len(errors) == 1


def test_an_unwritable_directory_does_not_raise(tmp_path):
    blocker = tmp_path / "notadir"
    blocker.write_text("")           # a file where the parent dir must go
    errors = []

    s = Stats(blocker / "stats.sqlite", on_error=errors.append)

    assert not s.available
    assert errors


# ----- schema versioning -----

def test_a_new_database_is_stamped(tmp_path):
    import sqlite3 as sq
    from idasen_companion.daemon.stats import SCHEMA_VERSION
    path = tmp_path / "stats.sqlite"
    Stats(path).close()
    with sq.connect(str(path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_an_unstamped_existing_database_is_adopted(tmp_path):
    """Files written before the stamp existed report 0 and match the schema as
    written, so they upgrade in place rather than being refused."""
    import sqlite3 as sq
    from idasen_companion.daemon.stats import SCHEMA_VERSION
    path = tmp_path / "stats.sqlite"

    s = Stats(path)
    s.add_active_time("sitting", 60, date(2026, 7, 17))
    s.close()
    with sq.connect(str(path)) as db:      # pretend it predates the stamp
        db.execute("PRAGMA user_version = 0")

    errors = []
    reopened = Stats(path, on_error=errors.append)
    assert reopened.available
    assert errors == []
    assert ("2026-07-17", "sitting", 60.0) in reopened.daily_totals(
        date(2026, 7, 17), date(2026, 7, 17))
    reopened.close()
    with sq.connect(str(path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_a_newer_database_is_refused_not_half_read(tmp_path):
    """A downgrade must not read a newer file as if it were current — it would
    return partial rows and look like data loss."""
    import sqlite3 as sq
    from idasen_companion.daemon.stats import SCHEMA_VERSION
    path = tmp_path / "stats.sqlite"
    Stats(path).close()
    with sq.connect(str(path)) as db:
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")

    errors = []
    s = Stats(path, on_error=errors.append)

    assert not s.available
    assert len(errors) == 1
    assert "newer version" in errors[0]
    assert s.daily_totals(date(2026, 7, 1), date(2026, 7, 2)) == []
