"""The scope-span naming checker (scripts/check_naming_span.py) must not drift.

The script isn't part of the importable package -- it's a standalone entry
point next to build-translations.sh, loaded here by path the same way a
`python scripts/check_naming_span.py` invocation would run it. Every test
drives it over a fixture written to `tmp_path`, never over the real tree:
a test that asserted against the real source would go red the moment a
rename plan in this phase lands, which is the opposite of what pinning this
checker's own behaviour is for.
"""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_naming_span.py"

_spec = importlib.util.spec_from_file_location("check_naming_span", SCRIPT)
check_naming_span = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_naming_span)


def _write(tmp_path, source):
    """Write `source` as a module and return its path."""
    path = tmp_path / "sample.py"
    path.write_text(source)
    return path


def test_a_short_name_over_its_band_reports(tmp_path):
    # 1-character name: stored at line 10, last read at line 20 -> span 10.
    lines = ["def f():"] + ["    pass"] * 8 + ["    e = 1"] + ["    pass"] * 9
    lines.append("    print(e)")
    path = _write(tmp_path, "\n".join(lines) + "\n")

    assert check_naming_span.main([str(path)]) == 1


def test_a_short_name_within_its_band_does_not_report(tmp_path):
    # 1-character name: stored at line 10, last read at line 13 -> span 3.
    lines = ["def f():"] + ["    pass"] * 8 + ["    e = 1", "    pass", "    pass"]
    lines.append("    print(e)")
    path = _write(tmp_path, "\n".join(lines) + "\n")

    assert check_naming_span.main([str(path)]) == 0


def test_a_four_character_name_is_never_banded(tmp_path):
    # A 4+ character name has no limit at all, however long it lives.
    # store at line 2, read at line 202 -> span 200.
    lines = ["def f():", "    name = 1"] + ["    pass"] * 199 + ["    print(name)"]
    path = _write(tmp_path, "\n".join(lines) + "\n")

    assert check_naming_span.main([str(path)]) == 0


def test_the_underscore_placeholder_never_reports(tmp_path):
    lines = ["def f():", "    _ = 1"] + ["    pass"] * 48 + ["    print(_)"]
    path = _write(tmp_path, "\n".join(lines) + "\n")

    assert check_naming_span.main([str(path)]) == 0


def test_a_name_stored_but_never_read_does_not_report(tmp_path):
    path = _write(tmp_path, "def f():\n    unread_but_long_name = 1\n")

    assert check_naming_span.main([str(path)]) == 0


def test_a_comprehension_target_does_not_report_against_the_enclosing_function(
        tmp_path):
    # The outer `x` is used right next to its assignment (span well within
    # band). The comprehension binds its own `x`, well past the band away --
    # if that read were wrongly folded into the outer function's span, this
    # would report; it must not.
    lines = ["def f():", "    x = 1", "    print(x)"]
    lines += ["    pass"] * 15
    lines.append("    return [x * 2 for x in range(3)]")
    path = _write(tmp_path, "\n".join(lines) + "\n")

    assert check_naming_span.main([str(path)]) == 0


def test_a_for_target_used_only_in_its_own_short_loop_does_not_report(tmp_path):
    path = _write(tmp_path, "def f():\n    for i in range(3):\n        print(i)\n")

    assert check_naming_span.main([str(path)]) == 0


def test_leading_underscores_do_not_count_toward_the_name_length(tmp_path):
    # `_t` bands as a 1-character name (limit 5), not 2 characters (limit 8).
    # A span of 6 reports under the 1-character band and would not under the
    # 2-character one, so this pins the stripping, not just a report/no-report.
    lines = ["def f():", "    _t = 1"] + ["    pass"] * 5 + ["    print(_t)"]
    path = _write(tmp_path, "\n".join(lines) + "\n")

    assert check_naming_span.main([str(path)]) == 1


def test_a_nested_def_is_measured_as_its_own_scope(tmp_path, capsys):
    lines = [
        "def outer():",
        "    def inner():",
        "        e = 1",
    ]
    lines += ["        pass"] * 6
    lines.append("        print(e)")
    lines.append("    return inner")
    path = _write(tmp_path, "\n".join(lines) + "\n")

    assert check_naming_span.main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "in inner()" in out
    assert "in outer()" not in out


def test_zero_hits_exits_0(tmp_path):
    path = _write(tmp_path, "def f():\n    pass\n")

    assert check_naming_span.main([str(path)]) == 0


def test_one_or_more_hits_exits_1(tmp_path):
    lines = ["def f():", "    e = 1"] + ["    pass"] * 10 + ["    print(e)"]
    path = _write(tmp_path, "\n".join(lines) + "\n")

    assert check_naming_span.main([str(path)]) == 1


def test_the_hit_output_format_matches_exactly(tmp_path, capsys):
    lines = ["def f():", "    e = 1"] + ["    pass"] * 10 + ["    print(e)"]
    path = _write(tmp_path, "\n".join(lines) + "\n")

    check_naming_span.main([str(path)])
    out = capsys.readouterr().out

    assert out == f"{path}:2: 'e' in f() lives 11 lines (max 5)\n"


def test_hits_are_sorted_by_path_then_line(tmp_path, capsys):
    first = tmp_path / "a_module.py"
    second = tmp_path / "b_module.py"
    body = ["def f():", "    e = 1"] + ["    pass"] * 10 + ["    print(e)"]
    first.write_text("\n".join(body) + "\n")
    second.write_text("\n".join(body) + "\n")

    check_naming_span.main([str(tmp_path)])
    out = capsys.readouterr().out.splitlines()

    assert out == sorted(out)
    assert str(first) in out[0]


def test_the_checker_pulls_in_nothing_beyond_the_stdlib():
    text = SCRIPT.read_text()
    modules = {
        match.split()[1].split(".")[0]
        for match in re.findall(r"^(?:import|from) .+", text, re.M)
    }
    stdlib_only = {"argparse", "ast", "pathlib", "sys"}
    assert modules <= stdlib_only
