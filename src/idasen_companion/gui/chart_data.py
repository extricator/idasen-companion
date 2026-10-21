"""Qt-free duration roles for the statistics chart."""

from typing import NamedTuple

from ..core.durations import Duration


class DailyChartRow(NamedTuple):
    """One calendar day's chart values, in the existing tuple order."""

    label: str
    sitting: Duration
    standing: Duration
    is_today: bool
