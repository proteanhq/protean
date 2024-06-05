from protean import Domain, handle
from protean.fields import Identifier, String

domain = Domain(__file__, load_toml=False)


@domain.event_sourced_aggregate
class User:
    id = Identifier()
    email = String()
    name = String()


@domain.command(part_of=User)
class Register:
    user_id = Identifier()
    email = String()


@domain.command(part_of=User)
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
