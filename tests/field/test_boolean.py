import pytest

from protean.fields.basic import Boolean


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ("t", True),
        ("f", False),
        ("True", True),
        ("False", False),
        (1.0, True),
        (0.0, False),
    ],
)
def test_boolean_cast_to_type(value, expected):
    field = Boolean()
    assert field._cast_to_type(value) == expected
