"""The Python type the SQLAlchemy adapter reads off a field to pick its column.

Fields declared with ``choices`` resolve through a ``Literal`` and are covered
in ``test_choices_column_mapping.py``. Nothing here opens a connection.
"""

import pytest

from protean.adapters.repository.sqlalchemy import _resolve_python_type
from protean.core.aggregate import BaseAggregate
from protean.fields import Dict, String
from protean.utils.reflection import attributes

pytestmark = pytest.mark.no_test_domain


class Profile(BaseAggregate):
    name: String(max_length=50, required=True)
    nickname: String(max_length=50)
    tags: list[str]
    settings: Dict()
    counts: dict[str, int]


class TestResolvedPythonType:
    def test_a_required_string_resolves_to_str(self):
        assert _resolve_python_type(attributes(Profile)["name"]) is str

    def test_an_optional_string_resolves_to_str(self):
        """An optional field is ``str | None``; the ``None`` arm is dropped."""
        assert _resolve_python_type(attributes(Profile)["nickname"]) is str

    def test_a_typed_list_resolves_to_list(self):
        assert _resolve_python_type(attributes(Profile)["tags"]) is list

    @pytest.mark.parametrize("attribute", ["settings", "counts"])
    def test_a_dict_field_resolves_to_dict(self, attribute):
        """``Dict()`` is ``dict | list`` and resolves to its first arm.
        ``dict[str, int]`` drops its type arguments."""
        assert _resolve_python_type(attributes(Profile)[attribute]) is dict
