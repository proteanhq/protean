import pytest

from protean.core.aggregate import BaseAggregate, element_to_fact_event
from protean.core.event import BaseEvent
from protean.utils.reflection import declared_fields


class University(BaseAggregate):
    name: str | None = None


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(University, fact_events=True)
    test_domain.init(traverse=False)


def test_fact_event_class_generation():
    event_cls = element_to_fact_event(University)

    assert event_cls.__name__ == "UniversityFactEvent"
    assert issubclass(event_cls, BaseEvent)
    assert len(declared_fields(event_cls)) == 2

    assert all(
        field_name in declared_fields(event_cls) for field_name in ["name", "id"]
    )
