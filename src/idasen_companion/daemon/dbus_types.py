# SPDX-License-Identifier: GPL-3.0-or-later
"""Typed D-Bus declarations across the supported distribution versions."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dbus_fast.annotations import (
        DBusBool, DBusDouble, DBusInt32, DBusUInt32, DBusStr, DBusSignature,
    )
    from dbus_fast.service import dbus_method, dbus_signal, dbus_property
else:
    try:
        from dbus_fast.annotations import (
            DBusBool, DBusDouble, DBusInt32, DBusUInt32, DBusStr, DBusSignature,
        )
    except ModuleNotFoundError as error:
        if error.name != "dbus_fast.annotations":
            raise
        from .dbus_legacy import (
            DBusBool, DBusDouble, DBusInt32, DBusUInt32, DBusStr, DBusSignature,
            dbus_method, dbus_signal, dbus_property,
        )
    else:
        from dbus_fast.service import dbus_method, dbus_signal, dbus_property
