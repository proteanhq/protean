from protean import Domain, current_domain, use_case
from protean.fields import Identifier, String

domain = Domain(name="Auth")


@domain.aggregate
class User:
    email: String()
    name: String()
    status: String(choices=["INACTIVE", "ACTIVE", "ARCHIVED"], default="INACTIVE")

    @classmethod
    def register(cls, email: str, name: str):
        return cls(email=email, name=name)

    def activate(self):
        self.status = "ACTIVE"


# --8<-- [start:service]
@domain.application_service(part_of=User)
class UserApplicationServices:
    @use_case
    def register_user(self, email: str, name: str) -> Identifier:
        user = User.register(email, name)
        current_domain.repository_for(User).add(user)
        return user.id  # Return the new entity's identifier

    @use_case
    def activate_user(self, user_id: Identifier) -> None:
        user = current_domain.repository_for(User).get(user_id)
        user.activate()
        current_domain.repository_for(User).add(user)
        # No return value needed for mutative operations

    @use_case
    def get_user(self, user_id: Identifier) -> User:
        return current_domain.repository_for(User).get(user_id)


# --8<-- [end:service]


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        service = UserApplicationServices()
        user_id = service.register_user(email="john@example.com", name="John Doe")
        service.activate_user(user_id)
        print(service.get_user(user_id).status)  # ACTIVE
