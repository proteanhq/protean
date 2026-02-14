import mock

from protean.core.aggregate import BaseAggregate
from protean.core.application_service import BaseApplicationService, use_case
from protean.core.event import BaseEvent
from protean.utils.globals import current_domain


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None


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


@mock.patch("protean.utils.mixins.UnitOfWork.__enter__")
@mock.patch("protean.utils.mixins.UnitOfWork.__exit__")
def test_that_method_is_enclosed_in_uow(mock_exit, mock_enter, test_domain):
    test_domain.register(User)
    test_domain.register(UserApplicationServices, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.init(traverse=False)

    mock_parent = mock.Mock()

    mock_parent.attach_mock(mock_enter, "m1")
    mock_parent.attach_mock(mock_exit, "m2")

    app_services_obj = UserApplicationServices()
    app_services_obj.register_user(email="john.doe@gmail.com", name="John Doe")

    mock_parent.assert_has_calls(
        [
            mock.call.m1(),
            mock.call.m2(None, None, None),
        ]
    )
