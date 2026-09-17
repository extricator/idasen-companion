"""Transitional name for the shared Babel-backed English locale profile."""

from __future__ import annotations

from ..locale_profile import LocaleProfile


class PlainLocaleFormatter(LocaleProfile):
    """Compatibility adapter using the deterministic English source locale."""

    def __init__(self) -> None:
        super().__init__("en_US")
