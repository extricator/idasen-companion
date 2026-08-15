"""The About page's Libraries row, and the two names every package has.

What the callers pass is an *import* name. It usually doubles as the
distribution name, which is why asking for the version straight off it works
most of the time — but install ``PySide6-Essentials`` (as the dev venv does)
and nothing is distributed under the name ``PySide6`` at all. The mapping
between the two is in the installed metadata, so these pin that it gets asked,
rather than a hand-written list of the exceptions being kept in step.

Skipped where PySide6 is missing, since the RPM lists it as a runtime
``Requires`` rather than a ``BuildRequires`` and the spec's ``%check`` may run
this suite without it.
"""

import sys
from importlib.metadata import PackageNotFoundError

import pytest

pytest.importorskip("PySide6")

import os

# Forced, not defaulted — see tests/test_settings_form.py for why.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from idasen_companion.gui.pages import about as about_mod  # noqa: E402
from idasen_companion.gui.pages.about import AboutPage  # noqa: E402


@pytest.fixture
def env(monkeypatch):
    """Stand in for the installed environment: what is distributed, and what
    imports. Modules go through ``sys.modules`` rather than a stubbed
    ``__import__``, so nothing else in the process has its imports rewritten.
    """

    class Env:
        dists: dict[str, str] = {}       # distribution name -> version
        provides: dict[str, list] = {}   # import name -> distributions

        @staticmethod
        def installed(name, module):
            monkeypatch.setitem(sys.modules, name, module)

    def version(name):
        try:
            return Env.dists[name]
        except KeyError:
            raise PackageNotFoundError(name) from None

    monkeypatch.setattr(about_mod, "version", version)
    monkeypatch.setattr(about_mod, "packages_distributions",
                        lambda: Env.provides)
    return Env


def test_the_usual_case_where_both_names_match(env):
    env.dists = {"bleak": "3.0.2"}
    assert AboutPage._lib_version("bleak") == "3.0.2"


def test_a_module_whose_distribution_is_named_differently(env):
    # The live case: the venv installs PySide6-Essentials, which provides the
    # PySide6 import. Nothing is distributed as "PySide6".
    env.provides = {"PySide6": ["PySide6_Essentials"]}
    env.dists = {"PySide6_Essentials": "6.11.1"}
    assert AboutPage._lib_version("PySide6") == "6.11.1"


def test_the_first_distribution_that_can_answer_wins(env):
    env.provides = {"PIL": ["Pillow-SIMD", "pillow"]}
    env.dists = {"pillow": "11.0.0"}   # the other is listed but not installed
    assert AboutPage._lib_version("PIL") == "11.0.0"


def test_an_installed_module_with_no_metadata_at_all(env):
    class Module:
        __version__ = "0.13.1"

    env.installed("metadataless_lib", Module)
    assert AboutPage._lib_version("metadataless_lib") == "0.13.1"


def test_a_module_that_is_simply_not_installed(env):
    # "?" is the honest answer, not a failure. Named for nothing real, so the
    # result doesn't depend on what happens to be installed where this runs —
    # which matters more than it sounds, since the single-RPM build runs the
    # suite against its own private library directory.
    assert AboutPage._lib_version("no_such_lib_anywhere") == "?"


def test_a_module_present_but_silent_about_its_version(env):
    env.installed("mystery_lib", object())
    assert AboutPage._lib_version("mystery_lib") == "?"
