# SPDX-License-Identifier: GPL-3.0-or-later
"""Authoritative strict status wording in both shipped languages."""

import pytest

from language_context import installed_language
from idasen_companion import cli
from idasen_companion.core.config import AppConfig
from idasen_companion.core.strict_state import StrictState


@pytest.mark.parametrize(("mode", "english", "spanish"), [
    ("standing", "Strict mode: Standing", "Modo estricto: De pie"),
    ("sitting", "Strict mode: Sitting", "Modo estricto: Sentado"),
    ("both", "Strict mode: Both", "Modo estricto: Ambos"),
])
def test_enabled_selection_without_an_enforced_interval(qapp, mode, english, spanish):
    state = StrictState(mode, "released", None, None)
    for language, expected in (("en", english), ("es", spanish)):
        with installed_language(language):
            fmt = cli._formatter(AppConfig())
            assert fmt.strict_status(state, "supported") == expected


def test_off_and_unconfigured_unavailable_status_are_hidden(qapp):
    fmt = cli._formatter(AppConfig())
    assert fmt.strict_status(StrictState("off", "released", None, None), "supported") == ""
    assert fmt.strict_status(None, "unknown") == ""
    assert fmt.strict_status(None, "unsupported") == ""


def test_selection_is_not_the_current_posture_and_unavailability_is_not_off(qapp):
    state = StrictState("both", "arrived", "standing", 1.1)
    for language, both, unsupported, unknown in (
        ("en", "Strict mode: Both", "Strict mode: service version unsupported.", "Strict mode: status unavailable."),
        ("es", "Modo estricto: Ambos", "Modo estricto: versión del servicio no compatible.", "Modo estricto: estado no disponible."),
    ):
        with installed_language(language):
            fmt = cli._formatter(AppConfig())
            assert fmt.strict_status(state, "supported") == both
            assert fmt.strict_status(state, "unsupported", configured_mode="both") == unsupported
            assert fmt.strict_status(None, "unknown", configured_mode="both") == unknown
