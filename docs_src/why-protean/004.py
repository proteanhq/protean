from protean import Domain, apply
from protean.fields import Float

domain = Domain()


# --8<-- [start:event_sourced]
@domain.event(part_of="Account")
class Deposited:
    amount: Float(required=True)


@domain.aggregate(event_sourced=True)
class Account:
    balance: Float(default=0.0)

    @apply
    def deposited(self, event: Deposited):
        self.balance += event.amount


# --8<-- [end:event_sourced]
