# --8<-- [start:update_email]
from protean import Domain, handle
from protean.fields import Identifier, String
from protean.utils.globals import current_domain

domain = Domain(name="Users")


@domain.aggregate
class User:
    user_id: Identifier(identifier=True)
    email: String(required=True)


@domain.command(part_of=User)
class UpdateEmail:
    user_id: Identifier(identifier=True)
    new_email: String(required=True)


@domain.command_handler(part_of=User)
class UserCommandHandler:
    @handle(UpdateEmail)
    def update_email(self, command: UpdateEmail) -> None:
        repo = current_domain.repository_for(User)
        user = repo.get(command.user_id)
        user.email = command.new_email
        repo.add(user)
        # Naturally idempotent: setting email to the same value
        # produces the same aggregate state.


# --8<-- [end:update_email]
