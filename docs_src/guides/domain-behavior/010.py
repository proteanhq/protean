from datetime import date

from protean import Domain
from protean.fields import HasMany
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class Patron:
    name: Annotated[str, Field(max_length=50)]
    status: str = Field(
        default="ACTIVE", json_schema_extra={"choices": ["ACTIVE", "INACTIVE"]}
    )
    holds = HasMany("Hold")

    def cancel_hold(self, hold_id):
        self.get_one_from_holds(id=hold_id).cancel_hold()


@domain.event(part_of="Patron")
class HoldCanceled:
    hold_id: str
    book_id: str
    patron_id: str
    canceled_on: date = date.today()


@domain.entity(part_of="Patron")
class Hold:
    book_id: str
    status: str = Field(
        default="ACTIVE",
        json_schema_extra={"choices": ["ACTIVE", "EXPIRED", "CANCELLED"]},
    )
    placed_on: date = date.today()

    def cancel_hold(self):
        self.status = "CANCELLED"
        self.raise_(
            HoldCanceled(
                hold_id=self.id,
                book_id=self.book_id,
                patron_id=self._owner.id,  # (1)
            )
        )
