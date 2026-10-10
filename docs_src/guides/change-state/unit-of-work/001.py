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


# --8<-- [start:manual]
from protean import UnitOfWork


def confirm_order(order_id):
    with UnitOfWork():
        repo = domain.repository_for(Order)
        order = repo.get(order_id)
        order.confirm()
        repo.add(order)
        # Commit happens automatically when the block exits successfully


# --8<-- [end:manual]


# --8<-- [start:imperative]
def confirm_order_step_by_step(order_id):
    uow = UnitOfWork()
    uow.start()

    try:
        repo = domain.repository_for(Order)
        order = repo.get(order_id)
        order.confirm()
        repo.add(order)
        uow.commit()
    except Exception:
        uow.rollback()
        raise


# --8<-- [end:imperative]


# --8<-- [start:current_uow]
from protean import current_uow


def describe_saving() -> str:
    if current_uow and current_uow.in_progress:
        # A UoW is active, so changes will be committed when it exits
        return "changes wait for the commit"
    return "changes are saved at once"


# --8<-- [end:current_uow]


# --8<-- [start:nested]
def save_together(repo, a, b, c):
    with UnitOfWork():  # outermost: owns the transaction
        repo.add(a)
        with UnitOfWork():  # nested: joins the outer, does not commit on its own
            repo.add(b)
        repo.add(c)
        # a, b, and c all commit together when the outermost block exits,
        # and all roll back together if anything fails.


# --8<-- [end:nested]


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        order = Order(total=25.0)
        domain.repository_for(Order).add(order)
        confirm_order(order.id)
        print(domain.repository_for(Order).get(order.id).status)  # CONFIRMED
