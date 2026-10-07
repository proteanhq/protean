from datetime import UTC, datetime

from protean import Domain, current_domain, handle
from protean.exceptions import ExpectedVersionError, ValidationError
from protean.fields import Auto, DateTime, Identifier, String

domain = Domain(name="OptimisticConcurrencySeats")


# --8<-- [start:aggregate]
@domain.aggregate
class SeatReservation:
    reservation_id: Auto(identifier=True)
    event_id: Identifier(required=True)
    seat_number: String(required=True)
    status: String(default="available")
    reserved_by: Identifier()
    reserved_at: DateTime()

    def reserve(self, customer_id: str) -> None:
        """Reserve this seat for a customer."""
        if self.status != "available":
            raise ValidationError(
                {"seat": [f"Seat {self.seat_number} is already taken"]}
            )

        self.status = "reserved"
        self.reserved_by = customer_id
        self.reserved_at = datetime.now(UTC)

        self.raise_(
            SeatReserved(
                reservation_id=self.reservation_id,
                event_id=self.event_id,
                seat_number=self.seat_number,
                customer_id=customer_id,
            )
        )


# --8<-- [end:aggregate]


@domain.event(part_of=SeatReservation)
class SeatReserved:
    reservation_id: Identifier(required=True)
    event_id: Identifier(required=True)
    seat_number: String(required=True)
    customer_id: Identifier(required=True)


# --8<-- [start:handler]
@domain.command(part_of=SeatReservation)
class ReserveSeat:
    reservation_id: Identifier(required=True)
    customer_id: Identifier(required=True)


class SeatAlreadyTaken(Exception):
    """Raised when a seat reservation fails because
    another customer reserved the seat first."""

    def __init__(self, seat_number: str):
        self.seat_number = seat_number
        super().__init__(f"Seat {seat_number} was just reserved by another customer")


@domain.command_handler(part_of=SeatReservation)
class ReservationCommandHandler:
    @handle(ReserveSeat)
    def reserve_seat(self, command: ReserveSeat):
        repo = current_domain.repository_for(SeatReservation)
        reservation = repo.get(command.reservation_id)

        try:
            reservation.reserve(command.customer_id)
            repo.add(reservation)
        except ExpectedVersionError:
            # Another customer reserved this seat between our
            # load and commit. This is not a transient failure:
            # it means the seat is genuinely taken.
            raise SeatAlreadyTaken(reservation.seat_number) from None


# --8<-- [end:handler]
