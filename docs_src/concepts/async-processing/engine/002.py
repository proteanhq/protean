from protean import Domain, current_domain, handle
from protean.fields import Boolean, Identifier, String

domain = Domain(name="Identity")


# --8<-- [start:user]
@domain.aggregate
class User:
    user_id: Identifier(identifier=True)
    email: String(required=True)
    active: Boolean(default=True)


@domain.command(part_of=User)
class RegisterUser:
    user_id: Identifier(identifier=True)
    email: String(required=True)


@domain.command(part_of=User)
class DeactivateUser:
    user_id: Identifier(identifier=True)


# --8<-- [end:user]


# --8<-- [start:handlers]
# Two command handlers for the same aggregate
@domain.command_handler(part_of=User)
class RegisterUserHandler:
    @handle(RegisterUser)
    def register(self, command):
        user = User(user_id=command.user_id, email=command.email)
        current_domain.repository_for(User).add(user)


@domain.command_handler(part_of=User)
class DeactivateUserHandler:
    @handle(DeactivateUser)
    def deactivate(self, command):
        repo = current_domain.repository_for(User)
        user = repo.get(command.user_id)
        user.active = False
        repo.add(user)


# The engine creates ONE subscription keyed as "commands:{stream_category}"
# that routes RegisterUser → RegisterUserHandler
# and DeactivateUser → DeactivateUserHandler
# --8<-- [end:handlers]
