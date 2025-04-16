from protean.domain import Domain
from protean.domain.registry import _DomainRegistry

domain = Domain(".")


# Base abstract event class
@domain.event(part_of="Sample", abstract=True)
class BaseEvent:
    base_id: str
    base_name: str

# Subclassing the abstract event
@domain.event(part_of="Sample")
class ConcreteEvent(BaseEvent):
    event_id: int
    description: str

def test_type_information_registered():
    registry: _DomainRegistry = domain.registry

    # Get the fully qualified name for the class
    fq_name = f"{ConcreteEvent.__module__}.{ConcreteEvent.__qualname__}"

    event_record = registry.events[fq_name]

    # Check if own fields and inherited fields are registered
    assert "event_id" in event_record.own_fields
    assert "description" in event_record.own_fields

    # Get the abstract base class FQN
    base_fq_name = f"{BaseEvent.__module__}.{BaseEvent.__qualname__}"

    assert base_fq_name in event_record.base_fields
    assert "base_id" in event_record.base_fields[base_fq_name]
    assert "base_name" in event_record.base_fields[base_fq_name]
