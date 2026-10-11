# --8<-- [start:imports]
from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.fields import ValueObject

# --8<-- [end:imports]
# isort: split

from protean import Domain

domain = Domain(name="Events")


# --8<-- [start:defaults]
class Venue(BaseValueObject):
    street: str = ""
    city: str | None = "Unknown"


class Event(BaseAggregate):
    venue = ValueObject(Venue)


# Before: Event(venue_street="1 Main St").venue.city is None
# After:  Event(venue_street="1 Main St").venue.city == "Unknown"
# --8<-- [end:defaults]

domain.register(Venue)
domain.register(Event)


# --8<-- [start:keep_none]
def event_without_a_city():
    # To keep None, pass it
    return Event(venue_street="1 Main St", venue_city=None)


# --8<-- [end:keep_none]
