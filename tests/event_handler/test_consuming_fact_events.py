import pytest

from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.event_handler import BaseEventHandler
from protean.core.projection import BaseProjection
from protean.utils.eventing import Message
from protean.utils.mixins import handle


class User(BaseAggregate):
    name: str
    email: str
    status: str | None = None


class UserProjection(BaseProjection):
    id: str = Field(json_schema_extra={"identifier": True})
    name: str
    email: str
    status: str


class ManageUserProjection(BaseEventHandler):
    @handle("Test.UserFact.v1")
    def record_user_fact_event(self, message: Message) -> None:
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, fact_events=True)
    test_domain.init(traverse=False)
