# --8<-- [start:model]
from protean import Domain, current_domain, handle
from protean.fields import Float, Identifier, String

domain = Domain(name="Sales")


# --8<-- [start:order]
@domain.aggregate
class Order:
    customer_id: String(required=True)
    total: Float(min_value=0)
    status: String(default="new")

    def place(self):
        self.status = "placed"
        self.raise_(OrderPlaced(order_id=self.id))  # Required


# --8<-- [end:order]


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)


@domain.command(part_of=Order)
class PlaceOrder:
    customer_id: String(required=True)


# --8<-- [end:model]


# --8<-- [start:sync_config]
domain.config["command_processing"] = "sync"
domain.config["event_processing"] = "sync"
# --8<-- [end:sync_config]


# --8<-- [start:check_handler]
def registered_handler():
    # Call this in a test or shell, after domain.init()
    with domain.domain_context():
        handlers = domain.command_handler_for(PlaceOrder(customer_id="cust-1"))
        print(handlers)  # Should show your handler class
        return handlers


# --8<-- [end:check_handler]


# --8<-- [start:command_handler]
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        order = Order(customer_id=command.customer_id)
        order.place()
        # This line is required -- without it, nothing is persisted
        current_domain.repository_for(Order).add(order)


# --8<-- [end:command_handler]


# --8<-- [start:event_handler]
# The handler must declare part_of matching the event's aggregate
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced): ...


# --8<-- [end:event_handler]


# --8<-- [start:engine]
from protean.server import Engine


def process_pending_messages():
    engine = Engine(domain=domain, test_mode=True)
    engine.run()


# --8<-- [end:engine]


# --8<-- [start:script]
def all_orders():
    with domain.domain_context():
        repo = domain.repository_for(Order)
        orders = repo.query.all()
    return orders


# --8<-- [end:script]


# --8<-- [start:projection]
@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)
    status: String()


# --8<-- [end:projection]


# --8<-- [start:projector]
@domain.projector(projector_for=OrderSummary, aggregates=[Order])
class OrderSummaryProjector:
    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced):
        current_domain.repository_for(OrderSummary).add(
            OrderSummary(order_id=event.order_id, status="placed")
        )


# --8<-- [end:projector]


# --8<-- [start:setup_database]
def create_tables():
    with domain.domain_context():
        domain.setup_database()


# --8<-- [end:setup_database]


# --8<-- [start:subscriber]
@domain.subscriber(stream="external_orders")
class OrderSubscriber:
    def __call__(self, payload: dict): ...


# --8<-- [end:subscriber]


# --8<-- [start:validation]
from protean.exceptions import ValidationError


def show_validation_errors():
    try:
        Order(customer_id="", total=-5)
    except ValidationError as e:
        print(e.messages)
        # {'customer_id': ['String should have at least 1 character'],
        #  'total': ['Input should be greater than or equal to 0']}


# --8<-- [end:validation]


# --8<-- [start:causation_tree]
def causation_tree(correlation_id):
    with domain.domain_context():
        tree = domain.event_store.store.build_causation_tree(correlation_id)
        # Returns a CausationNode: the command, with its events as .children
    return tree


# --8<-- [end:causation_tree]


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        domain.process(PlaceOrder(customer_id="cust-1"))
    print(all_orders().first.status)  # placed
