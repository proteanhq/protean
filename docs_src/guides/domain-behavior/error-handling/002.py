from protean import Domain
from protean.fields import String

domain = Domain()


# --8<-- [start:cancel]
from protean.exceptions import InvalidStateError


@domain.aggregate
class Order:
    status = String(default="draft")

    def cancel(self):
        if self.status == "shipped":
            raise InvalidStateError("Cannot cancel a shipped order")
        self.status = "cancelled"


# --8<-- [end:cancel]
