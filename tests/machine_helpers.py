"""Fresh deterministic setup shared by the state-machine behavior tests."""

import random

from idasen_companion.core.lengths import Length
from idasen_companion.core.config import AppConfig
from idasen_companion.core.machine import StateMachine
from idasen_companion.desk.mock import MockDesk

SIT_H = Length(0.62)
STAND_H = Length(1.10)
OFF_CYCLE_H = Length(0.95)  # not within tolerance of either preset target


def make_config(**automation_overrides) -> AppConfig:
    cfg = AppConfig()
    a = cfg.automation
    a.sit_duration = 45 * 60
    a.stand_duration = 25 * 60
    a.sit_variation = 0  # deterministic by default
    a.stand_variation = 0
    a.check_interval = 60
    a.idle_threshold = 10 * 60
    a.recent_input_threshold = 3 * 60
    a.sync_interval = 5 * 60
    for key, value in automation_overrides.items():
        setattr(a, key, value)
    cfg.presets = {"sit": SIT_H.metres, "stand": STAND_H.metres}
    return cfg


class ZeroRng(random.Random):
    def randint(self, a, b):
        return 0


class MaxRng(random.Random):
    def randint(self, a, b):
        return b


class Driver:
    def __init__(self, cfg=None, height=SIT_H, rng=None, now=1_000_000.0):
        self.cfg = cfg or make_config()
        self.desk = MockDesk(height)
        self.now = now
        self.m = StateMachine(self.cfg, self.desk, now=self.now, rng=rng or ZeroRng())

    async def start(self):
        return await self.m.start(self.now)

    async def tick(self, dt=60, idle_ms=1000, locked=False, away=False,
                   seatless=False):
        self.now += dt
        return await self.m.tick(self.now, idle_ms, locked, away, seatless)

    async def run_active_ticks(self, n, **kw):
        events = []
        for _ in range(n):
            events.extend(await self.tick(**kw))
        return events
