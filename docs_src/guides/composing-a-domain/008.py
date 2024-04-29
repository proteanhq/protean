from protean import Domain, handle
from protean.fields import Identifier, String

domain = Domain(__file__)


@domain.event_sourced_aggregate
class User:
    id = Identifier()
    email = String()
    name = String()


@domain.command(aggregate_cls=User)
class Register:
    user_id = Identifier()
    email = String()


@domain.command(aggregate_cls=User)
class ChangePassword:
    old_password_hash = String()
    new_password_hash = String()


@domain.command_handler
class UserCommandHandlers:
    @handle(Register)
    def register(self, command: Register) -> None:
        pass

    @handle(ChangePassword)
    def change_password(self, command: ChangePassword) -> None:
        pass
