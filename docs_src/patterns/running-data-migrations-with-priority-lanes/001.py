# --8<-- [start:model]
from protean import Domain, handle
from protean.fields import Float, Identifier, String
from protean.utils.globals import current_domain

domain = Domain(
    name="Identity",
    config={
        "command_processing": "sync",
        "server": {
            "default_subscription_type": "stream",
            "priority_lanes": {"enabled": True, "threshold": 0},
        },
    },
)


@domain.aggregate
class Customer:
    name: String(required=True)
    lifetime_spend: Float(default=0.0)
    loyalty_tier: String()

    def assign_tier(self, tier: str) -> None:
        self.loyalty_tier = tier
        self.raise_(LoyaltyTierAssigned(customer_id=self.id, loyalty_tier=tier))


@domain.event(part_of=Customer)
class LoyaltyTierAssigned:
    customer_id: Identifier(required=True)
    loyalty_tier: String(required=True)


@domain.command(part_of=Customer)
class UpdateCustomerTier:
    customer_id: Identifier(required=True)
    loyalty_tier: String(required=True)


@domain.command_handler(part_of=Customer)
class CustomerCommandHandler:
    @handle(UpdateCustomerTier)
    def update_tier(self, command: UpdateCustomerTier) -> None:
        repo = current_domain.repository_for(Customer)
        customer = repo.get(command.customer_id)
        customer.assign_tier(command.loyalty_tier)
        repo.add(customer)


domain.init(traverse=False)
# --8<-- [end:model]


# --8<-- [start:script]
"""migrate_loyalty_tiers.py

Backfill loyalty_tier on all existing customers based on their
total lifetime spend. Uses Priority.LOW so that events produced
by this script are routed to the backfill lane.
"""

import logging
import sys
import time

from protean.utils.processing import Priority, processing_priority

logger = logging.getLogger(__name__)

TIER_THRESHOLDS = [
    (10000, "platinum"),
    (5000, "gold"),
    (1000, "silver"),
    (0, "bronze"),
]


def determine_tier(lifetime_spend: float) -> str:
    for threshold, tier in TIER_THRESHOLDS:
        if lifetime_spend >= threshold:
            return tier
    return "bronze"


def customers_in_batches(batch_size: int):
    # A query returns 100 records unless told otherwise, so page through
    # the table instead of reading it with a single `all()`.
    repo = domain.repository_for(Customer)
    offset = 0
    while True:
        page = repo.query.order_by("id").offset(offset).limit(batch_size).all()
        yield page
        if not page.has_next:
            return
        offset += batch_size


def run_migration(batch_size: int = 100, dry_run: bool = False):
    with domain.domain_context():
        total = domain.repository_for(Customer).query.all().total
        logger.info(f"Found {total} customers to migrate")

        if dry_run:
            logger.info("Dry run mode -- no changes will be made")
            return

        migrated = 0
        errors = 0
        start_time = time.time()

        # Wrap the entire migration in a LOW priority context.
        # Every command processed inside this block will produce
        # events tagged with priority=-50, routed to backfill.
        with processing_priority(Priority.LOW):
            for page in customers_in_batches(batch_size):
                for customer in page.items:
                    try:
                        tier = determine_tier(customer.lifetime_spend)
                        domain.process(
                            UpdateCustomerTier(
                                customer_id=customer.id,
                                loyalty_tier=tier,
                            )
                        )
                        migrated += 1
                    except Exception as exc:
                        logger.error(f"Failed to migrate customer {customer.id}: {exc}")
                        errors += 1

                elapsed = time.time() - start_time
                rate = migrated / elapsed if elapsed > 0 else 0
                logger.info(
                    f"Progress: {migrated + errors}/{total} "
                    f"({rate:.0f} records/sec, "
                    f"{migrated} migrated, {errors} errors)"
                )

        elapsed = time.time() - start_time
        logger.info(
            f"Migration complete: {migrated}/{total} migrated, "
            f"{errors} errors, {elapsed:.1f}s elapsed"
        )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    dry_run = "--dry-run" in sys.argv
    run_migration(dry_run=dry_run)
# --8<-- [end:script]
