# SPDX-License-Identifier: GPL-3.0-or-later
"""Adapt typed declarations to dbus-fast 2.x/3.x's string annotations."""

from dataclasses import dataclass
from functools import update_wrapper
from inspect import iscoroutinefunction
from types import FunctionType
from typing import Annotated, get_args, get_type_hints

from dbus_fast.service import dbus_property as legacy_property
from dbus_fast.service import method as legacy_method, signal as legacy_signal
from dbus_fast.signature import SignatureTree


@dataclass(frozen=True)
class DBusSignature:
    """The wire signature carried by a Python type annotation."""

    signature: str


DBusBool = Annotated[bool, DBusSignature("b")]
DBusDouble = Annotated[float, DBusSignature("d")]
DBusInt32 = Annotated[int, DBusSignature("i")]
DBusUInt32 = Annotated[int, DBusSignature("u")]
DBusStr = Annotated[str, DBusSignature("s")]


def _string_annotations(function):
    """Give the legacy decorator a copy without changing the typed function."""
    annotations = {}
    for name, annotation in get_type_hints(function, include_extras=True).items():
        signatures = [item.signature for item in get_args(annotation)
                      if isinstance(item, DBusSignature)]
        if len(signatures) != 1:
            raise TypeError(f"{function.__name__}.{name}: expected one D-Bus signature")
        annotations[name] = signatures[0]
    adapted = FunctionType(function.__code__, function.__globals__, function.__name__,
                           function.__defaults__, function.__closure__)
    update_wrapper(adapted, function)
    # inspect.signature follows __wrapped__ by default. The copy must expose
    # its converted annotations to the legacy decorators instead.
    del adapted.__wrapped__
    adapted.__kwdefaults__ = function.__kwdefaults__
    adapted.__annotations__ = annotations
    if len(SignatureTree(annotations.get("return", "")).types) < 2:
        return adapted

    # The compiled 2.44 runtime passes compound tuples through to a notifier
    # that requires a list. Normalize at the legacy boundary for both async
    # method replies and synchronous signals.
    if iscoroutinefunction(adapted):
        async def async_compound(*args, **kwargs):
            return list(await adapted(*args, **kwargs))
        return update_wrapper(async_compound, adapted)

    def compound(*args, **kwargs):
        return list(adapted(*args, **kwargs))
    return update_wrapper(compound, adapted)


def dbus_method(**options):
    return lambda function: legacy_method(**options)(_string_annotations(function))


def dbus_signal(**options):
    return lambda function: legacy_signal(**options)(_string_annotations(function))


def dbus_property(**options):
    return lambda function: legacy_property(**options)(_string_annotations(function))
