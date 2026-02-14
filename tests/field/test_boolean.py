"""Test boolean field coercion through domain objects.

Bool coercion handles: 1/0, True/False, 't'/'f' etc.
"""

import pytest

from protean.core.value_object import BaseValueObject
from protean.fields import Boolean


class BoolVO(BaseValueObject):
    flag = Boolean(required=True)


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
    ],
)
def test_boolean_coercion(value, expected):
    vo = BoolVO(flag=value)
    assert vo.flag == expected
