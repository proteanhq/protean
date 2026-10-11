import httpx

from protean import Domain, UnitOfWork
from protean.fields import String

domain = Domain(name="Ordering")


@domain.aggregate
class Order:
    customer = String()
    status = String(default="new")

    def confirm(self):
        self.status = "confirmed"


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


# --8<-- [start:commit_then_call]
def confirm_order(order_id, payload):
    with UnitOfWork():
        order = domain.repository_for(Order).get(order_id)
        order.confirm()
        domain.repository_for(Order).add(order)

    httpx.post("https://partner.example/webhook", json=payload)


# --8<-- [end:commit_then_call]
