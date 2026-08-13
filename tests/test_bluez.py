from dbus_fast import Variant

from idasen_companion.daemon.bluez import (
    looks_like_desk,
    merge_devices,
    parse_paired_desks,
)


def device(name=None, alias=None, address=None, paired=True):
    props = {"Paired": Variant("b", paired)}
    if name is not None:
        props["Name"] = Variant("s", name)
    if alias is not None:
        props["Alias"] = Variant("s", alias)
    if address is not None:
        props["Address"] = Variant("s", address)
    return {"org.bluez.Device1": props}


def test_parse_finds_paired_desks_only():
    objects = {
        "/org/bluez/hci0/dev_1": device("Desk 4823", address="E1:B2:C3:D4:E5:F6"),
        "/org/bluez/hci0/dev_2": device("Desk 9999", address="AA:00:00:00:00:01",
                                        paired=False),
        "/org/bluez/hci0/dev_3": device("JBL Speaker", address="AA:00:00:00:00:02"),
        "/org/bluez/hci0": {"org.bluez.Adapter1": {}},
    }
    assert parse_paired_desks(objects) == [("Desk 4823", "E1:B2:C3:D4:E5:F6")]


def test_parse_uses_alias_when_name_missing():
    objects = {"/d": device(alias="LINAK DPG", address="AA:00:00:00:00:03")}
    assert parse_paired_desks(objects) == [("LINAK DPG", "AA:00:00:00:00:03")]


def test_looks_like_desk():
    assert looks_like_desk("Desk 4823")
    assert looks_like_desk("desk")
    assert looks_like_desk("LINAK DPG controller")
    assert not looks_like_desk("Desktop PC")  # 'desk' must be a word prefix
    assert not looks_like_desk("JBL Speaker")


def test_merge_prefers_known_and_dedupes_case_insensitively():
    known = [("Desk 4823", "E1:B2:C3:D4:E5:F6")]
    scanned = [("Desk 4823", "e1:b2:c3:d4:e5:f6"), ("Desk 1111", "AA:BB:CC:DD:EE:FF")]
    merged = merge_devices(known, scanned)
    assert merged == [("Desk 4823", "E1:B2:C3:D4:E5:F6"),
                      ("Desk 1111", "AA:BB:CC:DD:EE:FF")]
