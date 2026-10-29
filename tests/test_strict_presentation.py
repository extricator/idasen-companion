# SPDX-License-Identifier: GPL-3.0-or-later
"""Authoritative strict status wording in both shipped languages."""

import pytest

from language_context import installed_language
from idasen_companion import cli
from idasen_companion.core.config import AppConfig
from idasen_companion.core.strict_state import StrictState


@pytest.mark.parametrize(("stage", "posture", "english", "spanish"), [
    ("pending", "standing", "Strict mode: moving to standing. If stopped, the desk will retry promptly.", "Modo estricto: moviendo a la posición de pie. Si se detiene, el escritorio volverá a intentarlo pronto."),
    ("pending", "sitting", "Strict mode: moving to sitting. If stopped, the desk will retry promptly.", "Modo estricto: moviendo a la posición sentado. Si se detiene, el escritorio volverá a intentarlo pronto."),
    ("arrived", "standing", "Strict mode: standing interval enforced.", "Modo estricto: intervalo de pie obligatorio."),
    ("arrived", "sitting", "Strict mode: sitting interval enforced.", "Modo estricto: intervalo sentado obligatorio."),
])
def test_active_posture_and_stage(qapp, stage, posture, english, spanish):
    state = StrictState("both", stage, posture, 1.0)
    for language, expected in (("en", english), ("es", spanish)):
        with installed_language(language):
            fmt = cli._formatter(AppConfig())
            assert fmt.strict_status(state, "supported") == expected
            assert fmt.strict_status(state, "supported", concise=True) in expected


def test_released_and_capability_uncertainty(qapp):
    state = StrictState("both", "released", None, None)
    for language, released, unsupported, unknown in (
        ("en", "Strict mode: no interval enforced; ordinary controls are available.", "Strict mode status is unavailable with this background service version.", "Strict mode status is currently unavailable."),
        ("es", "Modo estricto: ningún intervalo es obligatorio; los controles normales están disponibles.", "El estado del modo estricto no está disponible con esta versión del servicio en segundo plano.", "El estado del modo estricto no está disponible en este momento."),
    ):
        with installed_language(language):
            fmt = cli._formatter(AppConfig())
            assert fmt.strict_status(state, "supported") == released
            assert fmt.strict_status(state, "unsupported") == unsupported
            assert fmt.strict_status(state, "unknown") == unknown
            assert fmt.strict_status(None, "supported") == unknown
            assert len({fmt.strict_status(state, cap, concise=True) for cap in ("supported", "unsupported", "unknown")}) == 3
