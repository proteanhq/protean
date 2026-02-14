from protean import Domain, handle

domain = Domain()


@domain.aggregate(is_event_sourced=True)
class User:
    id: str | None = None
    email: str | None = None
    name: str | None = None


@domain.command(part_of=User)
class Register:
    user_id: str | None = None
    email: str | None = None


@domain.command(part_of=User)
class ChangePassword:
    old_password_hash: str | None = None
    new_password_hash: str | None = None


@domain.command_handler(part_of=User)
class UserCommandHandlers:
    @handle(Register)
    def register(self, command: Register) -> None:
        pass

    @handle(ChangePassword)
    def change_password(self, command: ChangePassword) -> None:
        pass
