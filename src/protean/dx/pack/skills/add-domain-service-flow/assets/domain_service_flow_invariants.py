"""
Domain service with comprehensive pre and post invariants.

This example demonstrates:
- Multiple pre-invariants for cross-aggregate validation
- Post-invariant to verify the result of the operation
- A plain __init__: registration wires the invariants, so the service does not
  call the base class __init__
- The service checks both aggregates but changes only the Room
- The Requester's reservation list is updated through an event and a command,
  and a repeated command for the same reservation changes nothing

Domain: A resource booking system where reserving a meeting room
requires checking room availability, requester authorization level,
and verifying the reservation was properly recorded.

The checks across Room and Requester run in one step, in the Room's
transaction. The Requester is updated later, in its own transaction, so it is
eventually consistent with the Room.

Processing is synchronous, so one ReserveRoom command runs the whole flow
in-process, with no broker and no server.

Usage:
    from domain_service_flow_invariants import ReserveRoom, Requester, Room, domain

    domain.init(traverse=False)
    with domain.domain_context():
        domain.repository_for(Room).add(Room(room_id="R-1", name="Oak", capacity=8))
        domain.repository_for(Requester).add(
            Requester(requester_id="P-1", name="Ann", authorization_level=2)
        )

        domain.process(
            ReserveRoom(reservation_id="RES-1", room_id="R-1", requester_id="P-1")
        )
        # Room R-1 is reserved by P-1, and P-1 lists reservation RES-1.
"""

from protean import Domain, current_domain, handle, invariant
from protean.exceptions import ValidationError
from protean.fields import Identifier, Integer, List, String

domain = Domain(__name__)

# Run the whole flow in-process: RoomReserved reaches the event handler when the
# unit of work that saves the room commits, and RecordReservation reaches its
# handler as soon as it is issued.
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --- Events ---


@domain.event(part_of="Room")
class RoomReserved:
    """Raised when a room is reserved."""

    reservation_id: Identifier(required=True)
    room_id: Identifier(required=True)
    requester_id: Identifier(required=True)


# --- Aggregates ---


@domain.aggregate
class Room:
    """Meeting room aggregate."""

    room_id: Identifier(identifier=True)
    name: String(required=True, max_length=100)
    capacity: Integer(required=True)
    status: String(default="available")
    reserved_by: Identifier()

    def reserve(self, reservation_id, requester_id):
        """Reserve this room and announce the reservation."""
        self.status = "reserved"
        self.reserved_by = requester_id
        self.raise_(
            RoomReserved(
                reservation_id=reservation_id,
                room_id=self.room_id,
                requester_id=requester_id,
            )
        )

    def release(self):
        """Release this room."""
        self.status = "available"
        self.reserved_by = None


@domain.aggregate
class Requester:
    """Person requesting a room reservation.

    `reservation_ids` lists the reservations recorded for this requester, so a
    repeated RecordReservation for the same reservation changes nothing.
    """

    requester_id: Identifier(identifier=True)
    name: String(required=True, max_length=100)
    authorization_level: Integer(default=1)
    reservation_ids: List(content_type=String)

    def record_reservation(self, reservation_id):
        """Track that this requester made a reservation."""
        self.reservation_ids = [*self.reservation_ids, reservation_id]


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

    The service changes only the Room. The Requester records the reservation
    when it receives RecordReservation.
    """

    def __init__(self, room, requester, reservation_id):
        self.room = room
        self.requester = requester
        self.reservation_id = reservation_id

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
        if len(self.requester.reservation_ids) >= MAX_RESERVATIONS_PER_REQUESTER:
            raise ValidationError({"_service": ["Maximum reservation limit reached"]})

    @invariant.post
    def room_must_be_reserved_by_requester(self):
        """After execution, room must be reserved by this requester."""
        if self.room.reserved_by != self.requester.requester_id:
            raise ValidationError(
                {"_service": ["Room reservation was not properly recorded"]}
            )

    def __call__(self):
        """Execute reservation on the Room."""
        self.room.reserve(self.reservation_id, self.requester.requester_id)


# --- Commands ---


@domain.command(part_of="Room")
class ReserveRoom:
    """Reserve a room. The caller supplies the reservation id."""

    reservation_id: Identifier(required=True)
    room_id: Identifier(required=True)
    requester_id: Identifier(required=True)


@domain.command(part_of="Requester")
class RecordReservation:
    """Record a reservation on the Requester."""

    requester_id: Identifier(required=True)
    reservation_id: Identifier(required=True)


# --- Command Handlers ---


@domain.command_handler(part_of=Room)
class RoomCommandHandler:
    @handle(ReserveRoom)
    def reserve(self, command: ReserveRoom):
        """Check both aggregates through the service, then persist the Room."""
        room_repo = current_domain.repository_for(Room)
        room = room_repo.get(command.room_id)
        requester = current_domain.repository_for(Requester).get(command.requester_id)

        ReserveRoomService(room, requester, command.reservation_id)()

        room_repo.add(room)


@domain.command_handler(part_of=Requester)
class RequesterCommandHandler:
    @handle(RecordReservation)
    def record(self, command: RecordReservation):
        """Record the reservation on the Requester, once."""
        repo = current_domain.repository_for(Requester)
        requester = repo.get(command.requester_id)
        if command.reservation_id in requester.reservation_ids:
            # Already applied. A redelivered RoomReserved reissues
            # RecordReservation, and recording it again would count it twice.
            return
        requester.record_reservation(command.reservation_id)
        repo.add(requester)


# --- The cross-aggregate link: an event handler in Room's cluster ---


@domain.event_handler(part_of=Room)
class RecordRequesterReservation:
    """React to Room's own RoomReserved event and update the Requester.

    The handler sits in Room's cluster, which owns RoomReserved. It hands off
    to Requester with a command, and Requester's command handler does the write.
    """

    @handle(RoomReserved)
    def on_room_reserved(self, event: RoomReserved):
        current_domain.process(
            RecordReservation(
                requester_id=event.requester_id,
                reservation_id=event.reservation_id,
            )
        )
