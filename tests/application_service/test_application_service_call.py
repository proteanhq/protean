from protean.core.aggregate import BaseAggregate
from protean.core.application_service import BaseApplicationService, use_case
from protean.core.event import BaseEvent
from protean.utils.globals import current_domain


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None
    status: str = "INACTIVE"

    def activate(self):
        self.status = "ACTIVE"


class Registered(BaseEvent):
    user_id: str | None = None
    email: str | None = None
    name: str | None = None


class UserApplicationServices(BaseApplicationService):
    @use_case
    def register_user(self, email: str, name: str) -> str:
        user = User(email=email, name=name)
        user.raise_(Registered(user_id=user.id, email=user.email, name=user.name))
        current_domain.repository_for(User).add(user)

        return user.id

    @use_case
    def activate_user(sefl, user_id: str) -> None:
        user = current_domain.repository_for(User).get(user_id)
        user.activate()
        current_domain.repository_for(User).add(user)


def test_application_service_method_invocation(test_domain):
    test_domain.register(User)
    test_domain.register(UserApplicationServices, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.init(traverse=False)

    app_services_obj = UserApplicationServices()

    user_id = app_services_obj.register_user(
        email="john.doe@gmail.com", name="John Doe"
    )
    assert user_id is not None

    app_services_obj.activate_user(user_id)
    user = current_domain.repository_for(User).get(user_id)
    assert user.status == "ACTIVE"
