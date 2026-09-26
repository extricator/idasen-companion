"""BleDesk connection-policy tests using a fake idasen library desk.

No hardware or BLE stack involved: the fake stands in for
idasen.IdasenDesk via the desk_factory injection point.
"""

import asyncio
import struct

from idasen_companion.desk.ble import BleDesk, _decode_height


class FakeIdasenDesk:
    def __init__(self):
        self.is_connected = False
        self.height = 0.62
        self.connect_failures = 0
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.wakeup_calls = 0
        self.moves = []

    async def connect(self):
        self.connect_calls += 1
        if self.connect_failures > 0:
            self.connect_failures -= 1
            raise TimeoutError("simulated BlueZ flake")
        self.is_connected = True
        await self.wakeup()  # the real idasen library wakes on connect

    async def disconnect(self):
        self.is_connected = False
        self.disconnect_calls += 1

    async def get_height(self):
        assert self.is_connected
        return self.height

    async def move_to_target(self, height):
        self.moves.append(height)
        self.height = height

    async def wakeup(self):
        self.wakeup_calls += 1

    async def stop(self):
        pass

    async def pair(self):
        pass


def make_desk(fake=None, **kw):
    fake = fake or FakeIdasenDesk()
    kw.setdefault("linger", 0.02)
    kw.setdefault("retry_delays", (0, 0, 0))
    desk = BleDesk("AA:BB:CC:DD:EE:FF", desk_factory=lambda mac, cb: fake, **kw)
    return desk, fake


async def test_on_demand_connects_then_lingers_then_disconnects():
    desk, fake = make_desk()
    assert await desk.get_height() == 0.62
    assert fake.is_connected  # still connected during linger window
    await asyncio.sleep(0.08)
    assert not fake.is_connected
    assert fake.disconnect_calls == 1


async def test_burst_operations_share_one_connection():
    desk, fake = make_desk()
    await desk.get_height()
    assert await desk.move_to(1.10) is True
    await desk.get_height()
    assert fake.connect_calls == 1
    await asyncio.sleep(0.08)
    assert fake.disconnect_calls == 1


async def test_persistent_mode_stays_connected():
    desk, fake = make_desk(connection_mode="persistent")
    await desk.get_height()
    await asyncio.sleep(0.08)
    assert fake.is_connected
    assert fake.disconnect_calls == 0
    await desk.disconnect()
    assert not fake.is_connected


async def test_reconnect_builds_a_fresh_client():
    # Reusing a BleakClient across a BlueZ disconnect is slow from cold, so a
    # reconnect must construct a new desk object rather than reuse the stale one.
    created = []

    def factory(mac, cb):
        fake = FakeIdasenDesk()
        created.append(fake)
        return fake

    desk = BleDesk("AA:BB:CC:DD:EE:FF", desk_factory=factory,
                   linger=0.02, retry_delays=(0, 0, 0))
    await desk.get_height()
    assert len(created) == 1
    await asyncio.sleep(0.08)          # linger elapses -> disconnect
    assert not created[0].is_connected
    await desk.get_height()            # cold reconnect
    assert len(created) == 2           # a brand-new object, not the stale one
    assert created[1].is_connected
    await desk.disconnect()


# ----- a disconnect that never answers must not wedge the desk -----
#
# bleak sends Device1.Disconnect on an untimed bus call, and does it holding
# BleDesk's lock. A connection whose bus stalled across a suspend therefore had
# a way to park every later desk operation for the life of the process, in
# complete silence.

class StalledIdasenDesk(FakeIdasenDesk):
    """A handle whose disconnect never returns, like an unanswered bus call."""

    async def disconnect(self):
        self.disconnect_calls += 1
        await asyncio.Event().wait()


async def test_a_disconnect_that_never_answers_gives_up_and_frees_the_lock():
    desk, fake = make_desk(StalledIdasenDesk(), disconnect_timeout=0.05)
    await desk.get_height()
    await desk.disconnect()
    assert fake.disconnect_calls == 1
    # The whole point: the next operation gets the lock rather than queueing
    # behind a coroutine that will never finish.
    await asyncio.wait_for(desk.get_height(), 1.0)
    desk._cancel_linger()  # that read armed one; it would stall again


async def test_cancellation_resistant_disconnect_still_has_a_deadline():
    class Resistant(FakeIdasenDesk):
        def __init__(self):
            super().__init__()
            self.finish = asyncio.Event()

        async def disconnect(self):
            self.disconnect_calls += 1
            try:
                await self.finish.wait()
            except asyncio.CancelledError:
                await self.finish.wait()
            self.is_connected = False

    desk, fake = make_desk(Resistant(), disconnect_timeout=0.02, linger=60)
    await desk.get_height()
    await asyncio.wait_for(desk.disconnect(), 1)
    assert fake.disconnect_calls == 1
    assert desk._desk is None
    assert desk.last_error and "no reply" in desk.last_error
    fake.finish.set()
    await asyncio.sleep(0)


async def test_a_stalled_handle_is_written_off_rather_than_reused():
    created = []

    def factory(mac, callback):
        fake = StalledIdasenDesk()
        created.append(fake)
        return fake

    desk = BleDesk("AA:BB:CC:DD:EE:FF", desk_factory=factory, linger=60,
                   retry_delays=(0, 0, 0), disconnect_timeout=0.05)
    await desk.get_height()
    await desk.disconnect()
    assert desk.last_error is not None, "a stalled disconnect went unreported"
    await desk.get_height()
    assert len(created) == 2, "reconnected through the handle that stalled"


async def test_hanging_height_read_is_bounded_and_releases_the_link():
    class HangingRead(FakeIdasenDesk):
        async def get_height(self):
            await asyncio.Event().wait()

    desk, fake = make_desk(HangingRead(), read_timeout=0.02, linger=60)
    assert await asyncio.wait_for(desk.get_height(), 1) is None
    assert fake.disconnect_calls == 1
    assert not fake.is_connected
    assert desk.last_error and "no reply" in desk.last_error
    desk._cancel_linger()


async def test_hanging_connect_is_bounded_and_next_read_can_try_again():
    class HangingConnect(FakeIdasenDesk):
        async def connect(self):
            self.connect_calls += 1
            await asyncio.Event().wait()

    made = []

    def factory(mac, callback):
        fake = HangingConnect() if not made else FakeIdasenDesk()
        made.append(fake)
        return fake

    desk = BleDesk("AA:BB:CC:DD:EE:FF", desk_factory=factory,
                   retry_delays=(), read_timeout=0.02, linger=60)
    assert await asyncio.wait_for(desk.get_height(), 1) is None
    assert await asyncio.wait_for(desk.get_height(), 1) == 0.62
    assert len(made) == 2
    await desk.disconnect()


async def test_hanging_connect_cannot_leave_a_move_queued_forever():
    class HangingConnect(FakeIdasenDesk):
        async def connect(self):
            self.connect_calls += 1
            await asyncio.Event().wait()

    desk, fake = make_desk(HangingConnect(), connect_timeout=0.02,
                           linger=60)
    assert await asyncio.wait_for(desk.move_to(1.10), 1) is False
    assert fake.moves == []
    assert desk.last_error and "no reply" in desk.last_error
    desk._cancel_linger()


async def test_stop_during_connect_prevents_a_late_move():
    class SlowConnect(FakeIdasenDesk):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.finish = asyncio.Event()

        async def connect(self):
            self.started.set()
            await self.finish.wait()
            await super().connect()

    desk, fake = make_desk(SlowConnect(), connection_mode="persistent")
    move = asyncio.create_task(desk.move_to(1.10))
    await asyncio.wait_for(fake.started.wait(), 1)
    await desk.stop()
    fake.finish.set()
    assert await asyncio.wait_for(move, 1) is False
    assert fake.moves == []
    assert not fake.is_connected


async def test_forgetting_the_handle_tells_the_daemon_the_link_is_gone():
    """The daemon caches Desk1.Connected from this callback. A handle dropped
    without a BlueZ PropertiesChanged behind it produces no callback of its
    own, so the flag would stay true forever."""
    changes = []
    desk, _ = make_desk(on_connection_change=changes.append)
    await desk.get_height()
    assert changes == [True]
    desk.forget_handle()
    assert changes == [True, False]
    assert desk.connected is False


async def test_connect_retries_through_transient_failures():
    fake = FakeIdasenDesk()
    fake.connect_failures = 2  # first two attempts flake, third succeeds
    desk, _ = make_desk(fake)
    assert await desk.get_height() == 0.62
    assert fake.connect_calls == 3


async def test_all_retries_exhausted_returns_gracefully():
    fake = FakeIdasenDesk()
    fake.connect_failures = 99
    errors = []
    desk, _ = make_desk(fake, on_error=errors.append)
    assert await desk.get_height() is None
    assert await desk.move_to(1.10) is False
    assert desk.last_error is not None
    assert errors  # transient errors reported, not swallowed silently


async def test_cold_move_wakes_once_via_connect():
    # On a fresh connection idasen's connect() already wakes the controller, so
    # BleDesk must not add a redundant second wakeup before the move.
    desk, fake = make_desk()
    await desk.move_to(1.10)
    assert fake.wakeup_calls == 1  # from connect(), not a duplicate
    assert fake.moves == [1.10]


async def test_warm_move_rewakes_without_reconnecting():
    # Reusing a connection that has sat idle skips connect() (and its wakeup),
    # so BleDesk re-wakes itself in case the controller dozed meanwhile.
    desk, fake = make_desk(connection_mode="persistent", wakeup_grace=0.01)
    await desk.get_height()          # fresh connect wakes once
    assert fake.wakeup_calls == 1
    await asyncio.sleep(0.05)        # idle past the grace window
    await desk.move_to(1.10)         # warm: no reconnect, BleDesk re-wakes
    assert fake.wakeup_calls == 2
    assert fake.connect_calls == 1
    assert fake.moves == [1.10]


async def test_read_then_move_does_not_rewake():
    # A tray gesture is two desk operations back to back: refresh_height()
    # then the move. The controller was woken microseconds earlier, so the
    # move must not re-wake it — this is the path where the optimisation used
    # to silently never fire, because the second _ensure_connected saw an
    # already-open connection and treated it as a lingering reuse.
    desk, fake = make_desk(connection_mode="persistent")
    await desk.get_height()
    await desk.move_to(1.10)
    assert fake.wakeup_calls == 1    # from connect() only
    assert fake.connect_calls == 1
    assert fake.moves == [1.10]


async def test_callbacks_fire():
    heights, connections = [], []
    desk, fake = make_desk(on_height=heights.append,
                           on_connection_change=connections.append)
    await desk.get_height()
    assert heights == [0.62]
    assert connections == [True]
    await desk.disconnect()


async def test_unconfigured_mac_fails_quietly_without_connecting():
    fake = FakeIdasenDesk()
    desk = BleDesk("", desk_factory=lambda mac, cb: fake,
                   linger=0.02, retry_delays=(0,))
    assert await desk.get_height() is None
    assert await desk.move_to(1.10) is False
    assert fake.connect_calls == 0  # never even tried
    assert desk.last_error == "no desk address configured"


async def test_stop_without_connection_is_noop():
    desk, fake = make_desk()
    await desk.stop()
    assert fake.connect_calls == 0


class SlowFakeDesk(FakeIdasenDesk):
    """A desk whose move_to_target ramps toward the target over several steps
    and honours a cooperative stop (mirrors the real idasen library, which
    loops writing the reference input until stopped or arrived)."""

    #: Per ramp step. Long enough that a loaded runner cannot finish the whole
    #: ramp while the test is still setting up — see the note on `underway`.
    STEP = 0.05

    def __init__(self):
        super().__init__()
        self._moving = False
        #: Set once a move has actually begun. Tests wait on this instead of
        #: sleeping a guessed interval: a fixed sleep that overshoots lets the
        #: first move *complete*, after which "preemption" is vacuously true
        #: and the test passes without exercising anything.
        self.underway = asyncio.Event()
        #: Ramps that ran to completion, i.e. were never preempted.
        self.completed = 0

    async def move_to_target(self, height):
        self.moves.append(height)
        self._moving = True
        start = self.height
        for i in range(1, 11):
            if not self._moving:
                return  # stopped partway
            await asyncio.sleep(self.STEP)
            self.height = start + (height - start) * i / 10
            self.underway.set()
        self._moving = False
        self.completed += 1

    async def stop(self):
        self._moving = False


async def test_new_move_preempts_one_in_flight():
    # A second target issued mid-move must win immediately (last-write-wins)
    # rather than wait for the first move to run to completion.
    fake = SlowFakeDesk()
    desk, _ = make_desk(fake, connection_mode="persistent")
    await desk.get_height()  # connect up front
    first = asyncio.ensure_future(desk.move_to(1.10))
    await asyncio.wait_for(fake.underway.wait(), timeout=5)  # one step done

    assert await desk.move_to(0.70) is True  # preempts and redirects
    assert await first is True
    assert abs(fake.height - 0.70) < 1e-9  # ended at the newer target, not 1.10
    assert fake.moves == [1.10, 0.70]
    assert desk._move_in_flight is False
    # The point of the test: the first ramp was cut short. Without this a
    # runner slow enough to let it finish would still satisfy everything above.
    assert fake.completed == 1, "the first move was not actually preempted"


def test_decode_height():
    # raw counts are tenths of a millimeter above minimum height (0.62 m)
    assert _decode_height(struct.pack("<HH", 0, 0)) == 0.62
    assert abs(_decode_height(struct.pack("<HH", 4800, 0)) - 1.10) < 1e-9
    assert abs(_decode_height(struct.pack("<HH", 6500, 0)) - 1.27) < 1e-9


async def test_notify_subscription_decodes_updates():
    class FakeClient:
        def __init__(self):
            self.callback = None

        async def start_notify(self, uuid, callback):
            self.callback = callback

    fake = FakeIdasenDesk()
    fake._client = FakeClient()
    heights = []
    desk, _ = make_desk(fake, on_height=heights.append, linger=1)
    await desk.get_height()
    # The subscription is scheduled off the connect critical path, so give the
    # scheduled task a turn to run before asserting it subscribed.
    await asyncio.sleep(0.01)
    assert fake._client.callback is not None
    fake._client.callback(None, bytearray(struct.pack("<HH", 4800, 30)))
    assert any(abs(h - 1.10) < 1e-9 for h in heights)
