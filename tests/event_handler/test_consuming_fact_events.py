import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event_handler import BaseEventHandler
from protean.core.view import BaseView
from protean.fields import String
from protean.utils.mixins import Message, handle


class User(BaseAggregate):
    name = String(max_length=50, required=True)
    email = String(required=True)
    status = String(choices=["ACTIVE", "ARCHIVED"])


class UserView(BaseView):
    id = String(identifier=True)
    name = String(max_length=50, required=True)
    email = String(required=True)
    status = String(required=True)


class ManageUserView(BaseEventHandler):
    @handle("Test.UserFact.v1")
    def record_user_fact_event(self, message: Message) -> None:
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, fact_events=True)
    test_domain.init(traverse=False)
