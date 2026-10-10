from protean import Domain
from protean.fields import String

domain = Domain(name="Accounts")


@domain.aggregate
class Account:
    email: String(required=True)


# --8<-- [start:handler]
@domain.command_handler(part_of=Account, retries=2, retry_exceptions=[ConnectionError])
class AccountCommandHandler: ...


# --8<-- [end:handler]
