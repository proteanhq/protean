from protean import Domain, current_domain, use_case
from protean.fields import Identifier, String

domain = Domain(name="Auth")


@domain.aggregate
class User:
    # A second user with the same email fails to save with a ValidationError.
    email: String(required=True, unique=True)
    name: String()

    @classmethod
    def register(cls, email: str, name: str):
        return cls(email=email, name=name)


# --8<-- [start:errors]
from protean.exceptions import ValidationError


@domain.application_service(part_of=User)
class UserApplicationServices:
    @use_case
    def register_user(self, email: str, name: str) -> Identifier:
        user = User.register(email, name)
        current_domain.repository_for(User).add(user)
        return user.id


# In the API layer
def register_john():
    try:
        user_service = UserApplicationServices()
        user_id = user_service.register_user(email="john@example.com", name="John Doe")
        return 201, user_id
    except ValidationError as exc:
        # The input broke a rule, such as a taken email
        return 400, exc.messages
    except Exception:
        # Anything else is unexpected
        return 500, "Internal server error"


# --8<-- [end:errors]


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        print(register_john())  # (201, the new user's id)
        print(register_john())  # (400, ...): the email is already taken
