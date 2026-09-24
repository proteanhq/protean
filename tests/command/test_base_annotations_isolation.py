"""A command's or event's fields never leak into its base class.

Before Python 3.14, once anything reads ``ModelMetaclass.__annotations__``,
``cls.__annotations__`` on a message class that declares no annotations of its
own returns the nearest base's dict. Converting assignment-style value object
fields must then leave that dict alone, or every later message of the same
kind inherits the field.
"""

import inspect
from collections.abc import Iterator

import pytest
from pydantic._internal._model_construction import ModelMetaclass

from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.value_object import BaseValueObject
from protean.fields import String, ValueObject
from protean.utils.reflection import declared_fields

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def metaclass_annotations_read() -> Iterator[None]:
    had_own = "__annotations__" in ModelMetaclass.__dict__
    ModelMetaclass.__annotations__
    yield
    if not had_own:
        del ModelMetaclass.__annotations__


class Address(BaseValueObject):
    street: String()


@pytest.mark.usefixtures("metaclass_annotations_read")
@pytest.mark.parametrize("base_cls", [BaseCommand, BaseEvent])
def test_assignment_style_value_object_does_not_reach_the_base(base_cls):
    base_annotations = inspect.get_annotations(base_cls)

    class WithAddress(base_cls):
        address = ValueObject(Address)

    class Later(base_cls):
        note: String()

    assert "address" in declared_fields(WithAddress)
    assert inspect.get_annotations(base_cls) == base_annotations
    assert "address" not in declared_fields(Later)
