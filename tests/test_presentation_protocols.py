"""Locks each presentation protocol's member set to a named allowlist.

BACK-02 says neither protocol exposes a locale-database field: no accessor
for the decimal separator, month names, AM/PM text or the first day of the
week. That rule erodes one accessor at a time — a backend author reaches for
"just one field, just for this case", it compiles, the suite stays green,
and the shared layer has quietly grown its own incomplete locale engine. A
grep for known field names cannot catch the *next* one; only walking the
protocol object itself, and comparing what it actually declares against a
set someone deliberately chose, catches an addition nobody names in advance.

So this enumerates each protocol's members from the protocol object,
never from source text, and asserts the result equals — in both
directions — a locked allowlist. Equality rather than a subset check
matters here too: removing a sanctioned member silently shrinks the
protocol's contract just as unsafely as growing it does, and only a
two-way comparison catches both.

The enumeration itself has to survive the CI matrix (.github/workflows/test.yml
runs 3.11 through 3.14). `typing.get_protocol_members` is the public,
stdlib-documented way to ask, but it only exists from 3.13 onward
(cpython gh-104873). Below that this falls back to the private
`typing._get_protocol_attrs`, which is present on 3.11 and 3.12 and returns
the identical member set (verified directly against this project's own
protocols on 3.11.12, 3.12.10 and 3.14.6 — not assumed from a changelog).
The fallback is reached through a `getattr` probe, so the private call
retires on its own once the project's floor rises past 3.13.

The allowlists below are not meant to be static forever. Phase 13 added a
plural-aware member to `Translator` when the notification delay's duration
formatting needed one, and that is a deliberate, reviewed edit to this file. What this
gate exists to make visible is the *other* kind of edit: widening an
allowlist casually, in the middle of an unrelated change, to get something
past the check rather than to declare a new capability on purpose.
"""

from __future__ import annotations

import typing

import pytest

from idasen_companion.core.presentation.protocols import LocaleFormatter, Translator

#: Each protocol's sanctioned member set, chosen deliberately and asserted
#: against structurally — see the module docstring for why this can grow
#: (a new operation, added at its point of use) but must never grow by
#: accident.
_ALLOWLISTS = {
    LocaleFormatter: frozenset({"number", "integer", "percent", "time", "date"}),
    Translator: frozenset({"message", "plural"}),
}


def get_protocol_members(proto: type) -> frozenset[str]:
    """Every member ``proto`` declares, read from the protocol object.

    Prefers the public ``typing.get_protocol_members`` (3.13+); falls back
    to the private ``typing._get_protocol_attrs`` on earlier interpreters,
    which the module docstring above records as verified to return an
    identical set on this project's CI matrix.
    """
    get_members = getattr(typing, "get_protocol_members", None)
    if get_members is not None:
        return frozenset(get_members(proto))
    # typing.get_protocol_members is 3.13+ only; see module docstring.
    return frozenset(typing._get_protocol_attrs(proto))  # pylint: disable=protected-access


@pytest.mark.parametrize("protocol,allowed", _ALLOWLISTS.items(),
                          ids=lambda v: getattr(v, "__name__", str(v)))
def test_protocol_members_match_locked_allowlist(protocol, allowed):
    actual = get_protocol_members(protocol)
    extra = actual - allowed
    missing = allowed - actual
    assert not extra and not missing, (
        f"{protocol.__name__} members drifted from its locked allowlist"
        f" (extra: {sorted(extra)}, missing: {sorted(missing)})"
    )
