from protean import Domain
from protean.fields import Auto, Identifier, List

domain = Domain(name="Fulfillment")


@domain.aggregate
class Shipment:
    shipment_id: Auto(identifier=True)


@domain.event(part_of=Shipment)
class ExternalOrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)


# --8<-- [start:consumer_test]
class TestExternalOrderPlacedConsumption:
    """Verify that we can consume OrderPlaced events from the Order domain."""

    def test_can_deserialize_order_placed(self, test_domain):
        # Simulate an event payload from the external domain
        external_payload = {
            "order_id": "ord-123",
            "customer_id": "cust-456",
            "items": [
                {"product_id": "prod-1", "quantity": 2},
                {"product_id": "prod-2", "quantity": 1},
            ],
            "total": 75.0,
            "placed_at": "2024-06-15T10:30:00Z",
            # Fields we don't use but should tolerate
            "customer_email": "user@example.com",
            "discount_code": "SAVE10",
        }

        # Keep only the fields this domain declares
        known = {"order_id", "customer_id", "items"}
        event = ExternalOrderPlaced(
            **{key: value for key, value in external_payload.items() if key in known}
        )

        assert event.order_id == "ord-123"
        assert event.customer_id == "cust-456"
        assert len(event.items) == 2


# --8<-- [end:consumer_test]
