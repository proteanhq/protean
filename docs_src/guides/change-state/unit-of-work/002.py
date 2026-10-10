from protean import Domain, exceptions
from protean.fields import Float, String

domain = Domain(name="Sales")


@domain.aggregate
class Order:
    total: Float(default=0.0)
    status: String(default="PENDING", choices=["PENDING", "CONFIRMED"])

    def confirm(self):
        # The status changes first, so a failed confirm leaves a changed
        # object behind. Only a commit would make the change permanent.
        self.status = "CONFIRMED"
        if self.total <= 0:
            raise exceptions.ValidationError(
                {"total": ["An empty order cannot be confirmed"]}
            )


# --8<-- [start:rollback]
from protean import UnitOfWork
from protean.exceptions import ValidationError


def try_to_confirm_order(order_id):
    try:
        with UnitOfWork():
            repo = domain.repository_for(Order)
            order = repo.get(order_id)
            order.confirm()  # May raise ValidationError
            repo.add(order)
            # If confirm() or add() raises, rollback happens automatically
    except ValidationError:
        # The UoW has already rolled back, no partial state was committed
        ...


# --8<-- [end:rollback]


# --8<-- [start:commit_errors]
from protean.exceptions import TransactionError


def save_order(order):
    try:
        with UnitOfWork():
            domain.repository_for(Order).add(order)
    except TransactionError as exc:
        # exc.extra_info contains:
        #   - original_exception: exception class name
        #   - original_message: error message
        #   - sessions: list of provider names involved
        #   - events_count: number of events that were pending
        #   - messages_count: number of broker messages pending
        return exc.extra_info
    return None


# --8<-- [end:commit_errors]
