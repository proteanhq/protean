from datetime import UTC, datetime

from protean import Domain, current_domain, handle
from protean.fields import Auto, DateTime, Identifier, String

domain = Domain(name="OptimisticConcurrencySeats")
domain.config["command_processing"] = "sync"


# --8<-- [start:aggregate]
class SeatAlreadyTaken(Exception):
    """Raised when a customer tries to reserve a seat
    that another customer has already reserved."""

    def __init__(self, seat_number: str):
        self.seat_number = seat_number
        super().__init__(f"Seat {seat_number} was just reserved by another customer")


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
            raise SeatAlreadyTaken(self.seat_number)

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


@domain.command_handler(part_of=SeatReservation)
class ReservationCommandHandler:
    @handle(ReserveSeat)
    def reserve_seat(self, command: ReserveSeat):
        repo = current_domain.repository_for(SeatReservation)
        reservation = repo.get(command.reservation_id)
        # If another customer reserves the seat before this commit, the
        # commit raises ExpectedVersionError and the framework runs this
        # handler again. The reload sees the seat taken, and reserve()
        # raises SeatAlreadyTaken.
        reservation.reserve(command.customer_id)
        repo.add(reservation)


# --8<-- [end:handler]


# --8<-- [start:api]
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()


@app.post("/events/{event_id}/seats/{seat_number}/reserve")
async def reserve_seat(event_id: str, seat_number: str, customer_id: str):
    try:
        domain.process(
            ReserveSeat(
                reservation_id=f"{event_id}-{seat_number}",
                customer_id=customer_id,
            )
        )
        return {"status": "reserved"}
    except SeatAlreadyTaken as exc:
        return JSONResponse(
            status_code=409,
            content={
                "error": str(exc),
                "suggestion": "Please choose a different seat.",
            },
        )


# --8<-- [end:api]
