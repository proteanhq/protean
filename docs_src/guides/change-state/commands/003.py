from protean import Domain, current_domain, handle
from protean.fields import Identifier, List, String

domain = Domain(name="Sales")

# --8<-- [start:sync_config]
# Configure default command processing as synchronous
domain.config["command_processing"] = "sync"  # or "async"

# --8<-- [end:sync_config]


@domain.aggregate
class Order:
    items: List(content_type=String)


@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(required=True)
    items: List(content_type=String, required=True)


@domain.command(part_of=Order)
class ReserveStock:
    order_id: Identifier(required=True)


@domain.command(part_of=Order)
class ChargeCard:
    order_id: Identifier(required=True)


# The deadline each ReserveStock command carried, in the order they ran.
reservation_deadlines = []


@domain.command_handler(part_of=Order)
class StockCommandHandler:
    @handle(ReserveStock)
    def reserve(self, command: ReserveStock):
        reservation_deadlines.append(command._metadata.headers.deadline)


# --8<-- [start:set_deadline]
from datetime import UTC, datetime, timedelta


def charge_by_deadline():
    # Absolute deadline
    return domain.process(
        ChargeCard(order_id="ord-42"),
        deadline=datetime.now(UTC) + timedelta(seconds=30),
    )


def charge_within_timeout():
    # Relative timeout, converted to an absolute deadline at submission,
    # so it survives queue delays
    return domain.process(ChargeCard(order_id="ord-42"), timeout=timedelta(seconds=30))


# --8<-- [end:set_deadline]


# --8<-- [start:read_deadline]
@domain.command_handler(part_of=Order)
class PaymentCommandHandler:
    @handle(ChargeCard)
    def charge_card(self, command: ChargeCard):
        deadline = command._metadata.headers.deadline
        # Charge the card here. This example hands the deadline back.
        return deadline


# --8<-- [end:read_deadline]


# --8<-- [start:expired]
from protean.exceptions import CommandExpiredError


def process_before(cmd, past_deadline):
    try:
        domain.process(cmd, asynchronous=False, deadline=past_deadline)
    except CommandExpiredError as exc:
        # The expired command's type string, and the deadline it missed
        return exc.command_type, exc.deadline


# --8<-- [end:expired]


# --8<-- [start:propagation]
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder):
        # ReserveStock inherits PlaceOrder's deadline automatically
        current_domain.process(ReserveStock(order_id=command.order_id))


# --8<-- [end:propagation]


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        print(charge_within_timeout())  # about 30 seconds from now
