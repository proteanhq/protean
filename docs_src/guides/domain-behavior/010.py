from datetime import date

from protean import Domain
from protean.fields import Date, HasMany, Identifier, String

domain = Domain()


@domain.aggregate
class Patron:
    name = String(required=True, max_length=50)
    status = String(choices=["ACTIVE", "INACTIVE"], default="ACTIVE")
    holds = HasMany("Hold")

    def cancel_hold(self, hold_id):
        self.get_one_from_holds(id=hold_id).cancel_hold()


@domain.event(part_of="Patron")
class HoldCanceled:
    hold_id = Identifier(required=True)
    book_id = Identifier(required=True)
    patron_id = Identifier(required=True)
    canceled_on = Date(default=date.today())


@domain.entity(part_of="Patron")
class Hold:
    book_id = Identifier(required=True)
    status = String(choices=["ACTIVE", "EXPIRED", "CANCELLED"], default="ACTIVE")
    placed_on = Date(default=date.today())

    def cancel_hold(self):
        self.status = "CANCELLED"
        self.raise_(
            HoldCanceled(
                hold_id=self.id,
                book_id=self.book_id,
                patron_id=self._owner.id,  # (1)
            )
        )
