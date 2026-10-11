from protean import Domain, handle
from protean.fields import Float, Identifier, String

domain = Domain(name="Accounts")


@domain.aggregate
class Account:
    email: String(required=True)


@domain.command(part_of=Account)
class DebitAccount:
    account_id: Identifier(required=True)
    amount: Float(required=True)


# --8<-- [start:handler]
@domain.command_handler(part_of=Account, retries=2, retry_exceptions=[ConnectionError])
class AccountCommandHandler:
    @handle(DebitAccount)
    def debit(self, command: DebitAccount):
        # Only a ConnectionError is retried. A TimeoutError propagates at once.
        ...


# --8<-- [end:handler]
