import re
import pytest
from jsonpatch import JsonPatch
from periodo import identifier


def substitute(s):
    chars = list(s)
    chars[2] = identifier.XDIGITS[
        (identifier.XDIGITS.index(chars[2]) + 1) % len(identifier.XDIGITS)
    ]
    return "".join(chars)


def transpose(s):
    chars = list(s)
    for i in range(-3, -(len(s) + 1), -1):
        if not chars[i] == chars[i + 1]:
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
            return "".join(chars)


def check_authority_id(authority_id, id_map):
    identifier.check(authority_id)
    assert re.match(r"^p0[%s]{5}$" % identifier.XDIGITS, authority_id)
    assert authority_id in id_map.values()


def check_period_id(period_id, authority_id, id_map):
    identifier.check(period_id)
    assert re.match(r"^%s[%s]{4}$" % (authority_id, identifier.XDIGITS), period_id)
    assert period_id in id_map.values()


def test_assert_valid_loose():
    # old style checksum
    identifier.assert_valid("3wskd4mmt", strict=False)
    # new style checksum
    identifier.assert_valid("jrrjb8spw", strict=False)


def test_assert_valid_strict():
    with pytest.raises(identifier.IdentifierException):
        # old style checksum
        identifier.assert_valid("3wskd4mmt")
    # new style checksum
    identifier.assert_valid("jrrjb8spw")


@pytest.mark.parametrize("alter", [substitute, transpose])
def test_check_altered_identifier(alter):
    aid = identifier.for_authority()
    identifier.check(aid)
    altered_aid = alter(aid)
    with pytest.raises(identifier.IdentifierException):
        identifier.check(altered_aid)

    pid = identifier.for_period(aid)
    identifier.check(pid)
    altered_pid = alter(pid)
    with pytest.raises(identifier.IdentifierException):
        identifier.check(altered_pid)


def test_id_has_wrong_shape():
    with pytest.raises(identifier.IdentifierException):
        identifier.check("p06rw8")  # authority id too short
    with pytest.raises(identifier.IdentifierException):
        identifier.check("p06rw87/669p")  # period id has slash


def test_generate_period_id():
    aid = identifier.for_authority()
    pid = identifier.for_period(aid)
    assert pid.startswith(aid)
    assert len(pid) == 11


def test_replace_skolem_ids_when_adding_items(load_json):
    data = load_json("test-data.json")
    original_patch = JsonPatch(load_json("test-patch-adds-items.json"))
    applied_patch, id_map = identifier.replace_skolem_ids(
        original_patch, data, set(), {}
    )
    xd = identifier.XDIGITS

    # check addition of new period
    assert re.match(
        r"^/authorities/p0trgkv/periods/p0trgkv[%s]{4}$" % xd,
        applied_patch.patch[0]["path"],
    )
    check_period_id(applied_patch.patch[0]["value"]["id"], "p0trgkv", id_map)

    # check addition of new authority
    assert re.match(r"^/authorities/p0[%s]{5}$" % xd, applied_patch.patch[1]["path"])
    authority_id = applied_patch.patch[1]["value"]["id"]
    check_authority_id(authority_id, id_map)

    # check each period in new authority
    periods = applied_patch.patch[1]["value"]["periods"]
    for period_id in periods.keys():
        check_period_id(period_id, authority_id, id_map)
        assert period_id == periods[period_id]["id"]

        # check that skolem IDs in prop values get replaced
        prop = "broader" if "broader" in periods[period_id] else "narrower"
        check_period_id(periods[period_id][prop], authority_id, id_map)

        # check that skolem IDs in prop value arrays get replaced
        for period_id in periods[period_id].get("derivedFrom", []):
            check_period_id(period_id, "p0trgkv", id_map)


def test_replace_skolem_ids_when_replacing_periods(load_json):
    data = load_json("test-data.json")
    original_patch = JsonPatch(load_json("test-patch-replaces-periods.json"))
    applied_patch, id_map = identifier.replace_skolem_ids(
        original_patch, data, set(), {}
    )
    assert applied_patch.patch[0]["path"] == original_patch.patch[0]["path"]

    period_id, period = list(applied_patch.patch[0]["value"].items())[0]
    assert period_id == period["id"]
    check_period_id(period_id, "p0trgkv", id_map)


def test_replace_skolem_ids_when_replacing_authorities(load_json):
    data = load_json("test-data.json")
    original_patch = JsonPatch(load_json("test-patch-replaces-authorities.json"))
    applied_patch, id_map = identifier.replace_skolem_ids(
        original_patch, data, set(), {}
    )
    assert applied_patch.patch[0]["path"] == original_patch.patch[0]["path"]

    authority_id, authority = list(applied_patch.patch[0]["value"].items())[0]
    assert authority_id == authority["id"]
    check_authority_id(authority_id, id_map)

    period_id, period = list(
        applied_patch.patch[0]["value"][authority_id]["periods"].items()
    )[0]
    assert period_id == period["id"]
    check_period_id(period_id, authority_id, id_map)
