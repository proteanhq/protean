from protean import Domain, current_domain, handle
from protean.fields import Identifier, String

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


# --8<-- [start:customer]
@domain.aggregate
class Customer:
    customer_id: Identifier(identifier=True)
    loyalty_tier: String(default="BRONZE")


@domain.command(part_of=Customer)
class UpdateCustomer:
    customer_id: Identifier(identifier=True)
    loyalty_tier: String(required=True)


# --8<-- [end:customer]


@domain.event(part_of=Customer)
class LoyaltyTierChanged:
    customer_id: Identifier(required=True)
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


# --8<-- [start:product]
@domain.aggregate
class Product:
    product_id: Identifier(identifier=True)


@domain.command(part_of=Product)
class ReindexProduct:
    product_id: Identifier(identifier=True)


# --8<-- [end:product]


@domain.event(part_of=Product)
class ProductReindexed:
    product_id: Identifier(required=True)


@domain.command_handler(part_of=Product)
class ProductCommandHandler:
    @handle(ReindexProduct)
    def reindex(self, command: ReindexProduct) -> None:
        product = Product(product_id=command.product_id)
        product.raise_(ProductReindexed(product_id=command.product_id))
        current_domain.repository_for(Product).add(product)


# --8<-- [start:context_manager]
from protean.utils.processing import Priority, processing_priority


def backfill_loyalty_tiers(migration_data):
    # All events produced within this block get LOW priority
    with processing_priority(Priority.LOW):
        for record in migration_data:
            domain.process(
                UpdateCustomer(
                    customer_id=record["id"],
                    loyalty_tier=record["tier"],
                )
            )


# --8<-- [end:context_manager]


# --8<-- [start:nested]
def process_nested(cmd1, cmd2, cmd3):
    with processing_priority(Priority.LOW):
        domain.process(cmd1)  # LOW

        with processing_priority(Priority.CRITICAL):
            domain.process(cmd2)  # CRITICAL

        domain.process(cmd3)  # LOW again


# --8<-- [end:nested]


# --8<-- [start:explicit]
def reindex_catalog():
    # This specific command gets BULK priority
    domain.process(
        ReindexProduct(product_id="SKU-001"),
        priority=Priority.BULK,
    )


# --8<-- [end:explicit]


# --8<-- [start:override]
def process_urgently(cmd):
    with processing_priority(Priority.LOW):
        # This command uses CRITICAL despite the LOW context
        domain.process(cmd, priority=Priority.CRITICAL)


# --8<-- [end:override]
