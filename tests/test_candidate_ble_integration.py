# SPDX-License-Identifier: GPL-3.0-or-later
"""Real client stack on a private bus with an in-memory GATT transport."""

import asyncio
import inspect
import os
import struct
from unittest.mock import AsyncMock, MagicMock

import pytest
from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.client import BaseBleakClient
from bleak.backends.service import BleakGATTService, BleakGATTServiceCollection
from dbus_fast import Message
from dbus_fast.aio import MessageBus
from dbus_fast.constants import BusType, MessageType, PropertyAccess
from dbus_fast.service import ServiceInterface, dbus_property
from idasen import IdasenDesk

from idasen_companion import DBUS_NAME, DBUS_PATH
from idasen_companion.core.lengths import Length
from idasen_companion.daemon.service import Desk1
from idasen_companion.desk.ble import BleDesk
from machine_helpers import Driver, make_config
from test_strict_retry import daemon_for_driver

BASE = "99fa{}-338a-1024-8a49-009c0215f78a"


class GattBackend(BaseBleakClient):
    """Only the transport is simulated; Bleak and idasen remain real."""

    instances = []

    def __init__(self, address, **kwargs):
        super().__init__(address, **kwargs)
        self.connected = False
        self.events = []
        self.height = 0.8
        self.block_read = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.services = BleakGATTServiceCollection()
        service = BleakGATTService(None, 1, BASE.format("0020"))
        self.services.add_service(service)
        for handle, short in enumerate(("0021", "0002", "0031", "0011"), 2):
            char = BleakGATTCharacteristic(None, handle, BASE.format(short),
                                           ["read", "write", "write-without-response", "notify"],
                                           lambda: 20, service)
            self.services.add_characteristic(char)
        self.instances.append(self)

    @property
    def mtu_size(self):
        return 23

    @property
    def is_connected(self):
        return self.connected

    async def connect(self, *_args, **_kwargs):
        self.connected = True
        self.events.append(("connect",))

    async def disconnect(self):
        self.connected = False
        self.events.append(("disconnect",))

    async def pair(self, **_kwargs):
        raise AssertionError("unexpected pairing")

    async def unpair(self):
        raise AssertionError("unexpected unpairing")

    async def read_gatt_char(self, characteristic, **_kwargs):
        self.events.append(("read", characteristic.uuid))
        if self.block_read:
            self.entered.set()
            await self.release.wait()
        return bytearray(struct.pack("<Hh", round((self.height - 0.62) * 10000), 0))

    async def write_gatt_char(self, characteristic, data, response):
        value = bytes(data)
        self.events.append(("write", characteristic.uuid, value))
        if characteristic.uuid == BASE.format("0031") and value != b"\x01\x80":
            self.height = 0.62 + int.from_bytes(value, "little") / 10000

    async def start_notify(self, characteristic, callback, **_kwargs):
        self.events.append(("notify", characteristic.uuid))
        self.callback = callback

    async def stop_notify(self, characteristic):
        self.events.append(("stop_notify", characteristic.uuid))

    async def read_gatt_descriptor(self, *_args, **_kwargs):
        raise AssertionError("unexpected descriptor read")

    async def write_gatt_descriptor(self, *_args, **_kwargs):
        raise AssertionError("unexpected descriptor write")


@pytest.fixture
def isolated_transport(monkeypatch):
    if "client" not in inspect.signature(IdasenDesk).parameters:
        pytest.skip("installed idasen does not support injected clients")
    if "/tmp/dbus-" not in os.environ.get("DBUS_SESSION_BUS_ADDRESS", ""):
        pytest.skip("requires a private dbus-run-session bus")

    original_init = MessageBus.__init__

    def session_only(self, bus_address=None, bus_type=BusType.SESSION, **kwargs):
        assert bus_type == BusType.SESSION and bus_address is None, "system bus forbidden"
        original_init(self, bus_address=bus_address, bus_type=bus_type, **kwargs)

    monkeypatch.setattr(MessageBus, "__init__", session_only)
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("unexpected Bluetooth discovery")
    monkeypatch.setattr(BleakScanner, "discover", forbidden)
    from bleak.backends.bluezdbus.client import BleakClientBlueZDBus
    monkeypatch.setattr(BleakClientBlueZDBus, "connect", forbidden)
    GattBackend.instances.clear()

    def factory(mac, callback):
        client = BleakClient(mac, backend=GattBackend, disconnected_callback=callback)
        return IdasenDesk(mac, client=client)

    return BleDesk("AA:BB:CC:DD:EE:FF", desk_factory=factory, linger=60,
                   on_height=lambda _height: None)


async def test_connect_move_disconnect(isolated_transport):
    desk = isolated_transport
    driver = Driver(make_config())
    await driver.start()
    daemon = daemon_for_driver(driver)
    daemon.desk = desk
    daemon.moving = False
    daemon._invalidate_position_observation = MagicMock()
    daemon._admit_strict_locked = AsyncMock()
    server, client = await MessageBus().connect(), await MessageBus().connect()
    server.export(DBUS_PATH, Desk1(daemon))
    await server.request_name(DBUS_NAME)
    try:
        reply = await asyncio.wait_for(client.call(Message(
            destination=DBUS_NAME, path=DBUS_PATH, interface=f"{DBUS_NAME}.Desk1",
            member="MoveToHeight", signature="d", body=[1.0])), 5)
        assert reply.message_type == MessageType.METHOD_RETURN, reply.body
        backend = GattBackend.instances[0]
        await desk._try_start_notify()
        assert ("connect",) in backend.events
        assert ("write", BASE.format("0002"), b"\xfe\x00") in backend.events
        assert any(event[:2] == ("read", BASE.format("0021")) for event in backend.events)
        assert any(event[:2] == ("write", BASE.format("0031")) for event in backend.events)
        assert ("notify", BASE.format("0021")) in backend.events
    finally:
        await desk.disconnect()
        await server.release_name(DBUS_NAME)
        client.disconnect()
        server.disconnect()
        await asyncio.sleep(0)
    assert not backend.connected


async def test_cancelled_inflight_read_allows_later_move(isolated_transport):
    desk = isolated_transport
    assert await desk.get_height() is not None
    backend = GattBackend.instances[0]
    backend.block_read = True
    move = asyncio.create_task(desk.move_to(Length(1.0)))
    try:
        await asyncio.wait_for(backend.entered.wait(), 2)
        move.cancel()
        with pytest.raises(asyncio.CancelledError):
            await move
        backend.block_read = False
        assert await asyncio.wait_for(desk.move_to(Length(1.0)), 2)
        assert any(event[:2] == ("write", BASE.format("0031")) for event in backend.events)
    finally:
        backend.release.set()
        await desk.disconnect()
    assert not backend.connected


async def test_stop_invalidates_pending_private_bus_move(isolated_transport):
    desk = isolated_transport
    assert await desk.get_height() is not None
    backend = GattBackend.instances[0]
    backend.block_read = True
    driver = Driver(make_config())
    await driver.start()
    daemon = daemon_for_driver(driver)
    daemon.desk, daemon.moving = desk, False
    daemon._invalidate_position_observation = MagicMock()
    daemon._admit_strict_locked = AsyncMock()
    server, client = await MessageBus().connect(), await MessageBus().connect()
    server.export(DBUS_PATH, Desk1(daemon))
    await server.request_name(DBUS_NAME)

    def message(member, signature="", body=None):
        return Message(destination=DBUS_NAME, path=DBUS_PATH,
                       interface=f"{DBUS_NAME}.Desk1", member=member,
                       signature=signature, body=body or [])

    move = asyncio.create_task(client.call(message("MoveToHeight", "d", [1.0])))
    stop = None
    try:
        await asyncio.wait_for(backend.entered.wait(), 2)
        stop = asyncio.create_task(client.call(message("Stop")))
        # Stop reaches the real adapter before the backend read is released.
        for _ in range(100):
            if desk._stop_generation:
                break
            await asyncio.sleep(0)
        assert desk._stop_generation == 1
        backend.block_read = False
        backend.release.set()
        assert (await asyncio.wait_for(stop, 2)).message_type == MessageType.METHOD_RETURN
        assert (await asyncio.wait_for(move, 2)).message_type == MessageType.METHOD_RETURN
        assert not any(event[:2] == ("write", BASE.format("0031")) and
                       event[2] != b"\x01\x80" for event in backend.events)
        reply = await asyncio.wait_for(client.call(message("MoveToHeight", "d", [1.0])), 2)
        assert reply.message_type == MessageType.METHOD_RETURN
        assert any(event[:2] == ("write", BASE.format("0031")) and
                   event[2] != b"\x01\x80" for event in backend.events)
    finally:
        backend.release.set()
        await asyncio.gather(move, *([stop] if stop else []), return_exceptions=True)
        await desk.disconnect()
        await server.release_name(DBUS_NAME)
        client.disconnect()
        server.disconnect()
        await asyncio.sleep(0)


class FakeBlueZDevice(ServiceInterface):
    def __init__(self):
        super().__init__("org.bluez.Device1")

    @dbus_property(access=PropertyAccess.READ)
    def Connected(self) -> "b":  # pylint: disable=invalid-name
        return True


async def test_release_preserves_other_real_client(isolated_transport):
    desk = isolated_transport
    assert await desk.get_height() is not None
    first = GattBackend.instances[0]
    other = BleDesk("11:22:33:44:55:66", desk_factory=desk._desk_factory, linger=60)
    assert await other.get_height() is not None
    second = GattBackend.instances[1]
    driver = Driver(make_config())
    await driver.start()
    daemon = daemon_for_driver(driver)
    daemon.desk, daemon.mock_mode = desk, False
    daemon.config.desk.mac = desk.mac
    server, client = await MessageBus().connect(), await MessageBus().connect()
    path = "/org/bluez/test/device"
    server.export(path, FakeBlueZDevice())
    await server.request_name("org.bluez")
    daemon.bluetooth = MagicMock()
    daemon.bluetooth.device_path.return_value = path

    async def property_read(device, interface, name):
        reply = await client.call(Message(destination="org.bluez", path=device,
                                          interface="org.freedesktop.DBus.Properties",
                                          member="Get", signature="ss", body=[interface, name]))
        assert reply.message_type == MessageType.METHOD_RETURN
        return reply.body[0].value

    daemon.bluetooth.property = property_read
    try:
        await daemon._recover_link_after_resume()
        assert not first.connected and second.connected
        assert await asyncio.wait_for(other.move_to(Length(1.0)), 2)
        assert second.connected
        daemon.activity_log.diag.assert_called_once()
    finally:
        await desk.disconnect()
        await other.disconnect()
        await server.release_name("org.bluez")
        client.disconnect()
        server.disconnect()
        await asyncio.sleep(0)
