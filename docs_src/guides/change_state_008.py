from protean import Domain, current_domain, use_case
from protean.fields import Identifier, String

auth = Domain(name="Auth")


@auth.aggregate
class User:
    email = String()
    name = String()
    status = String(choices=["INACTIVE", "ACTIVE", "ARCHIVED"], default="INACTIVE")

    @classmethod
    def register(cls, email: str, name: str):
        user = cls(email=email, name=name)
        user.raise_(Registered(user_id=user.id, email=user.email, name=user.name))

        return user

    def activate(self):
        self.status = "ACTIVE"


@auth.event(part_of=User)
class Registered:
    user_id = Identifier()
    email = String()
    name = String()


@auth.application_service(part_of=User)
class UserApplicationServices:
    @use_case
    def register_user(self, email: str, name: str) -> Identifier:
        user = User.register(email, name)
        current_domain.repository_for(User).add(user)

        return user.id

    @use_case
    def activate_user(sefl, user_id: Identifier) -> None:
        user = current_domain.repository_for(User).get(user_id)
        user.activate()
        current_domain.repository_for(User).add(user)


auth.register(User)
auth.register(UserApplicationServices, part_of=User)
auth.register(Registered, part_of=User)
auth.init(traverse=False)
