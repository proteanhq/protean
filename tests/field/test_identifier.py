from uuid import UUID, uuid4

from protean.fields import Identifier


def test_UUID_identifiers_are_converted_into_strings_in_as_dict():
    uuid_val = uuid4()
    identifier = Identifier()

    value = identifier._load(uuid_val)

    assert isinstance(value, UUID)
    assert identifier.as_dict(value) == str(uuid_val)


def test_int_identifiers_are_preserved_as_ints_in_as_dict():
    identifier = Identifier()

    value = identifier._load(42)

    assert isinstance(value, int)
    assert identifier.as_dict(value) == 42
