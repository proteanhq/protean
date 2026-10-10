from protean import Domain, handle
from protean.fields import Float, Identifier, String

domain = Domain(name="Accounts")


@domain.aggregate
class Account:
    email: String(required=True)


# --8<-- [start:handler]
@domain.command(part_of=Account)
class DebitAccount:
    account_id: Identifier(required=True)
    amount: Float(required=True)


@domain.command_handler(part_of=Account, retries=3, backoff="exponential")
class AccountCommandHandler:
    @handle(DebitAccount)
    def debit(self, command: DebitAccount):
        # A ConnectionError here is retried up to 3 times with
        # exponential backoff before propagating.
        ...


# --8<-- [end:handler]
