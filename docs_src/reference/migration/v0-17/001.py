from protean import Domain, UnitOfWork
from protean.fields import String

domain = Domain(name="Ordering")


@domain.aggregate
class Order:
    customer = String()


@domain.aggregate
class Audit:
    note = String()


# --8<-- [start:nested]
def place_order(order, entry):
    with UnitOfWork():
        domain.repository_for(Order).add(order)

        try:
            with UnitOfWork():  # joins the outer transaction
                domain.repository_for(Audit).add(entry)
                raise RuntimeError("audit failed")
        except RuntimeError:
            pass  # the exception is handled...

        # ...but on 0.17 the outer transaction is already doomed, and the
        # order is not saved either. On 0.16 the order was saved.


# --8<-- [end:nested]
