from collections import OrderedDict
from types import MappingProxyType

import pytest

from protean.utils import _ensure_template_dict


@pytest.mark.parametrize("value", [{"name": "John"}, OrderedDict(name="John")])
def test_dict_passes(value):
    assert _ensure_template_dict(value) is None


@pytest.mark.parametrize(
    "value", [["John"], "John", None, ("a", 1), MappingProxyType({"name": "John"})]
)
def test_non_dict_raises_type_error(value):
    with pytest.raises(TypeError) as exc:
        _ensure_template_dict(value)

    assert str(exc.value) == (
        f"Positional argument {value} passed must be a dict. "
        "This argument serves as a template for loading common values."
    )
