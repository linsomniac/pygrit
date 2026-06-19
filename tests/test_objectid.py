import pytest

HEX = "0123456789abcdef0123456789abcdef01234567"  # 40 hex = SHA-1


def test_objectid_from_hex_roundtrip():
    import pygritlib

    oid = pygritlib.ObjectId.from_hex(HEX)
    assert oid.hex == HEX
    assert oid.raw == bytes.fromhex(HEX)
    assert oid.hash_algorithm == "sha1"


def test_objectid_equality_and_hash():
    import pygritlib

    a = pygritlib.ObjectId.from_hex(HEX)
    b = pygritlib.ObjectId.from_hex(HEX)
    assert a == b
    assert hash(a) == hash(b)
    assert {a, b} == {a}


def test_objectid_repr():
    import pygritlib

    assert HEX in repr(pygritlib.ObjectId.from_hex(HEX))


def test_objectid_invalid_hex_raises():
    import pygritlib

    with pytest.raises((ValueError, pygritlib.InvalidObjectError)):
        pygritlib.ObjectId.from_hex("xyz")
