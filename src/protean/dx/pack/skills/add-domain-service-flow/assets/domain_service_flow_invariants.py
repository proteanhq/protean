"""
Domain service with comprehensive pre and post invariants.

This example demonstrates:
- Multiple pre-invariants for cross-aggregate validation
- Post-invariant to verify the result of the operation
- Explicit BaseDomainService.__init__ call pattern
- Service that coordinates resource allocation across aggregates

Domain: A resource booking system where reserving a meeting room
requires checking room availability, requester authorization level,
and verifying the reservation was properly recorded.
"""

from protean import Domain, invariant
from protean.core.domain_service import BaseDomainService
from protean.exceptions import ValidationError
from protean.fields import Identifier, Integer, String

domain = Domain(__name__)


# --- Aggregates ---


@domain.aggregate
class Room:
    """Meeting room aggregate."""

    room_id: Identifier(identifier=True)
    name: String(required=True, max_length=100)
    capacity: Integer(required=True)
    status: String(default="available")
    reserved_by: Identifier()

    def reserve(self, requester_id):
        """Reserve this room."""
        self.status = "reserved"
        self.reserved_by = requester_id

    def release(self):
        """Release this room."""
        self.status = "available"
        self.reserved_by = None


@domain.aggregate
class Requester:
    """Person requesting a room reservation."""

    requester_id: Identifier(identifier=True)
    name: String(required=True, max_length=100)
    authorization_level: Integer(default=1)
    reservation_count: Integer(default=0)

    def increment_reservations(self):
        """Track that this requester made a reservation."""
        self.reservation_count += 1


# --- Domain Service ---

MAX_RESERVATIONS_PER_REQUESTER = 3


@domain.domain_service(part_of=[Room, Requester])
class ReserveRoomService:
    """Reserve a meeting room for a requester.

    Pre-invariants:
    - Room must be available
    - Requester must have sufficient authorization
    - Requester must not exceed max reservations

    Post-invariant:
    - Room must be reserved by the correct requester
    """

    def __init__(self, room, requester):
        BaseDomainService.__init__(self, *(room, requester))
        self.room = room
        self.requester = requester

    @invariant.pre
    def room_must_be_available(self):
        """Room must be in available status."""
        if self.room.status != "available":
            raise ValidationError(
                {"_service": ["Room is not available for reservation"]}
            )

    @invariant.pre
    def requester_must_have_authorization(self):
        """Requester must have authorization level >= 2 for reservations."""
        if self.requester.authorization_level < 2:
            raise ValidationError(
                {"_service": ["Insufficient authorization level for room reservation"]}
            )

    @invariant.pre
    def requester_must_not_exceed_max_reservations(self):
        """Requester must not exceed the maximum reservation limit."""
        if self.requester.reservation_count >= MAX_RESERVATIONS_PER_REQUESTER:
            raise ValidationError({"_service": ["Maximum reservation limit reached"]})

    @invariant.post
    def room_must_be_reserved_by_requester(self):
        """After execution, room must be reserved by this requester."""
        if self.room.reserved_by != self.requester.requester_id:
            raise ValidationError(
                {"_service": ["Room reservation was not properly recorded"]}
            )

    def __call__(self):
        """Execute reservation: reserve room and track in requester."""
        self.room.reserve(self.requester.requester_id)
        self.requester.increment_reservations()
