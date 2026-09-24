"""A value object's fields never leak into ``BaseValueObject``.

Before Python 3.14, once anything reads ``ModelMetaclass.__annotations__``,
the metaclass holds a plain dict under that name. ``cls.__annotations__`` on a
model class that declares no annotations of its own then resolves through the
MRO and returns the parent's dict. Resolving fields must read only the class's
own annotations, or a nested value object declared in assignment style is
written into ``BaseValueObject`` and every later value object inherits it.
"""

import inspect
from collections.abc import Iterator

import pytest
from pydantic._internal._model_construction import ModelMetaclass

from protean.core.value_object import BaseValueObject
from protean.fields import String, ValueObject
from protean.utils.reflection import declared_fields


@pytest.fixture
def metaclass_annotations_read() -> Iterator[None]:
    had_own = "__annotations__" in ModelMetaclass.__dict__
    ModelMetaclass.__annotations__
    yield
    if not had_own:
        del ModelMetaclass.__annotations__


class Coordinates(BaseValueObject):
    latitude: float
    longitude: float


@pytest.mark.usefixtures("metaclass_annotations_read")
class TestBaseValueObjectAnnotationsStayClean:
    def test_assignment_style_nested_value_object_does_not_reach_the_base(self):
        base_annotations = inspect.get_annotations(BaseValueObject)

        class Location(BaseValueObject):
            city = String(max_length=50)
            coordinates = ValueObject(Coordinates)

        assert "coordinates" in declared_fields(Location)
        assert inspect.get_annotations(BaseValueObject) == base_annotations

    def test_later_value_object_has_only_its_own_fields(self):
        class Location(BaseValueObject):
            city = String(max_length=50)
            coordinates = ValueObject(Coordinates)

        class Tag(BaseValueObject):
            label: String()

        assert set(declared_fields(Tag)) == {"label"}
        assert Tag(label="x").to_dict() == {"label": "x"}
