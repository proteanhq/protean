from protean import Domain, handle
from protean.fields import Identifier, String

domain = Domain(name="Payments")


@domain.aggregate
class Order:
    status: String(default="PENDING")


@domain.command(part_of=Order)
class ConfirmPayment:
    order_id: Identifier(required=True)


@domain.command(part_of=Order)
class ReserveInventory:
    order_id: Identifier(required=True)


@domain.command(part_of=Order)
class NotifyWarehouse:
    order_id: Identifier(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(ConfirmPayment)
    def confirm_payment(self, command: ConfirmPayment) -> None: ...

    @handle(ReserveInventory)
    def reserve_inventory(self, command: ReserveInventory) -> None: ...

    @handle(NotifyWarehouse)
    def notify_warehouse(self, command: NotifyWarehouse) -> None: ...


# --8<-- [start:payments]
@domain.subscriber(stream="payments")
class PaymentSubscriber:
    def __call__(self, message):
        # The correlation_id from the source service is already in context.
        # Any commands dispatched here inherit it automatically.
        domain.process(
            ConfirmPayment(order_id=message["order_id"]),
        )


# --8<-- [end:payments]


# --8<-- [start:fulfillment]
@domain.subscriber(stream="fulfillment")
class FulfillmentSubscriber:
    def __call__(self, message):
        # Both commands inherit the same correlation_id from the broker message.
        domain.process(ReserveInventory(order_id=message["order_id"]))
        domain.process(NotifyWarehouse(order_id=message["order_id"]))


# --8<-- [end:fulfillment]
