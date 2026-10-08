# --8<-- [start:produce]
from protean import Domain
from protean.fields import Float, Identifier
from protean.utils.eventing import Message

domain = Domain(name="MyApp")
domain.config["source_uri"] = "https://orders.example.com"


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total: Float(required=True)


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    total: Float(required=True)

    def place(self):
        self.raise_(
            OrderPlaced(
                order_id=self.id, customer_id=self.customer_id, total=self.total
            )
        )


domain.init(traverse=False)

with domain.domain_context():
    order = Order(id="abc123", customer_id="cust-456", total=99.99)
    order.place()
    event = order._events[0]

    # Create a message from a domain event (as usual)
    message = Message.from_domain_object(event)

    # Serialize to CloudEvents format
    cloud_event = message.to_cloudevent()
# --8<-- [end:produce]

# --8<-- [start:consume]
import json

from protean.utils.eventing import Message

# The raw JSON body that a subscriber or API endpoint receives
body = json.dumps(cloud_event)

cloud_event_dict = json.loads(body)
message = Message.from_cloudevent(cloud_event_dict)
# --8<-- [end:consume]

# --8<-- [start:to-domain-object]
message = Message.from_cloudevent(cloud_event_dict)

# If the type is registered in this domain, reconstruct the event
with domain.domain_context():
    event = message.to_domain_object()
# --8<-- [end:to-domain-object]

# --8<-- [start:round-trip]
original = Message.from_domain_object(event)
ce = original.to_cloudevent()

# ... send over the wire ...

restored = Message.from_cloudevent(ce)
assert restored.data == original.data
assert restored.metadata.headers.id == original.metadata.headers.id
assert (
    restored.metadata.domain.correlation_id == original.metadata.domain.correlation_id
)
# --8<-- [end:round-trip]
