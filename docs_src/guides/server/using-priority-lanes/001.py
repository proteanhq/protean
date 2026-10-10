from protean import Domain, current_domain, handle
from protean.fields import Identifier, String

# --8<-- [start:import]
from protean.utils.processing import Priority, processing_priority

# --8<-- [end:import]

domain = Domain(
    name="CRM",
    config={
        "command_processing": "sync",
        "server": {
            "default_subscription_type": "stream",
            "priority_lanes": {
                "enabled": True,
                "threshold": 0,
                "backfill_suffix": "backfill",
            },
        },
    },
)


@domain.aggregate
class Customer:
    customer_id: Identifier(identifier=True)
    loyalty_tier: String(default="BRONZE")


@domain.event(part_of=Customer)
class LoyaltyTierChanged:
    customer_id: Identifier(required=True)
    loyalty_tier: String(required=True)


@domain.command(part_of=Customer)
class UpdateCustomer:
    customer_id: Identifier(identifier=True)
    loyalty_tier: String(required=True)


@domain.command_handler(part_of=Customer)
class CustomerCommandHandler:
    @handle(UpdateCustomer)
    def update(self, command: UpdateCustomer) -> None:
        customer = Customer(
            customer_id=command.customer_id, loyalty_tier=command.loyalty_tier
        )
        customer.raise_(
            LoyaltyTierChanged(
                customer_id=command.customer_id, loyalty_tier=command.loyalty_tier
            )
        )
        current_domain.repository_for(Customer).add(customer)


@domain.aggregate
class Product:
    product_id: Identifier(identifier=True)


@domain.event(part_of=Product)
class ProductReindexed:
    product_id: Identifier(required=True)


@domain.command(part_of=Product)
class ReindexProduct:
    product_id: Identifier(identifier=True)


@domain.command_handler(part_of=Product)
class ProductCommandHandler:
    @handle(ReindexProduct)
    def reindex(self, command: ReindexProduct) -> None:
        product = Product(product_id=command.product_id)
        product.raise_(ProductReindexed(product_id=command.product_id))
        current_domain.repository_for(Product).add(product)


records_to_process = [
    {"id": "cust-1", "tier": "GOLD"},
    {"id": "cust-2", "tier": "SILVER"},
]


# --8<-- [start:context_manager]
def backfill_loyalty_tiers():
    with processing_priority(Priority.LOW):
        for record in records_to_process:
            domain.process(
                UpdateCustomer(
                    customer_id=record["id"],
                    loyalty_tier=record["tier"],
                )
            )


# --8<-- [end:context_manager]


# --8<-- [start:explicit]
def reindex_catalog():
    domain.process(
        ReindexProduct(product_id="SKU-001"),
        priority=Priority.BULK,
    )


# --8<-- [end:explicit]
