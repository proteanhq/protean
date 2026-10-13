# --8<-- [start:account]
from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, String

domain = Domain()


@domain.aggregate
class Account:
    account_number: Identifier(required=True, unique=True)
    balance: Float(default=0.0)
    status: String(choices=["ACTIVE", "FROZEN"], default="ACTIVE")

    @invariant.pre
    def account_must_be_active_to_transact(self):
        if self.status == "FROZEN":
            raise ValidationError({"_entity": ["Cannot modify a frozen account"]})

    @invariant.post
    def balance_must_not_be_negative(self):
        if self.balance < 0:
            raise ValidationError({"_entity": ["Insufficient funds"]})

    def withdraw(self, amount: float):
        self.balance -= amount


# --8<-- [end:account]
