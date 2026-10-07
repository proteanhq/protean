from protean import Domain, handle
from protean.fields import String
from protean.utils.globals import current_domain

domain = Domain(name="Accounts")


# --8<-- [start:handler]
@domain.aggregate
class Account:
    email: String(required=True)
    name: String(required=True)


@domain.command(part_of=Account)
class RegisterCommand:
    email: String(required=True)
    name: String(required=True)


@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(RegisterCommand)
    def register(self, command: RegisterCommand) -> str:
        account = Account(email=command.email, name=command.name)
        current_domain.repository_for(Account).add(account)

        # Return the account ID for immediate use
        return account.id


# --8<-- [end:handler]


# --8<-- [start:process_sync]
def register_account(command):
    # Process command synchronously and get the return value
    result = domain.process(command, asynchronous=False)
    return result


# --8<-- [end:process_sync]


# --8<-- [start:process_async]
def submit_registration(command):
    # Process command asynchronously (default)
    position = domain.process(command)  # or domain.process(command, asynchronous=True)
    return position


# --8<-- [end:process_async]


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        account_id = register_account(
            RegisterCommand(email="jane@example.com", name="Jane Doe")
        )
        account = domain.repository_for(Account).get(account_id)
        print(account.email, account.name)
