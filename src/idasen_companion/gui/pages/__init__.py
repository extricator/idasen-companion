"""Main-window pages, one QWidget subclass per sidebar entry."""

from __future__ import annotations

from .about import AboutPage
from .activity_log import ActivityLogPage
from .automation import AutomationPage
from .base import Page
from .overview import OverviewPage
from .presets import PresetsPage
from .settings import SettingsPage
from .settings_form import SettingsFormPage
from .statistics import StatisticsPage

__all__ = [
    "Page",
    "SettingsFormPage",
    "OverviewPage",
    "AutomationPage",
    "PresetsPage",
    "StatisticsPage",
    "ActivityLogPage",
    "SettingsPage",
    "AboutPage",
]
