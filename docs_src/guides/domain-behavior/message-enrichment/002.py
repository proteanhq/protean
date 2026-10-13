from protean import Domain
from protean.fields import Identifier

domain = Domain()


@domain.event(part_of="Account")
class AccountOpened:
    account_id: Identifier(required=True)


@domain.aggregate
class Account:
    def open(self):
        self.raise_(AccountOpened(account_id=self.id))


# --8<-- [start:fifo]
@domain.event_enricher
def add_user(event, aggregate):
    return {"source": "user-enricher", "user_id": "u-123"}


@domain.event_enricher
def add_tenant(event, aggregate):
    return {"source": "tenant-enricher", "tenant_id": "t-456"}


# Result: {"source": "tenant-enricher", "user_id": "u-123", "tenant_id": "t-456"}
# --8<-- [end:fifo]
