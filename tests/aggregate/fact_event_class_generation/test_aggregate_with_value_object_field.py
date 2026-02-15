"""Test fact event class generation for aggregate with ValueObject field.

Covers uncovered lines 286-289 in aggregate.py:
- ValueObject descriptor handling in _pydantic_element_to_fact_event
"""

import pytest

from protean.core.aggregate import BaseAggregate, element_to_fact_event
from protean.core.event import BaseEvent
from protean.core.value_object import BaseValueObject
from protean.fields import String, ValueObject
from protean.utils.reflection import declared_fields


class File(BaseValueObject):
    url: String(max_length=1024)
    type: String(max_length=15)


class Resource(BaseAggregate):
    title: String(required=True, max_length=50)
    associated_file = ValueObject(File)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(File)
    test_domain.register(Resource, fact_events=True)
    test_domain.init(traverse=False)


def test_fact_event_includes_value_object_field():
    """Lines 286-289: ValueObject field is included in fact event."""
    event_cls = element_to_fact_event(Resource)

    assert event_cls.__name__ == "ResourceFactEvent"
    assert issubclass(event_cls, BaseEvent)
    assert "associated_file" in declared_fields(event_cls)
    assert "title" in declared_fields(event_cls)
    assert "id" in declared_fields(event_cls)
