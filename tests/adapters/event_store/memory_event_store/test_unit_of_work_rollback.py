"""An append to the memory event store survives a Unit of Work rollback."""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Identifier, String


class Registered(BaseEvent):
    id = Identifier()
    name = String()


class User(BaseAggregate):
    name = String()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.init(traverse=False)


def test_appended_event_is_read_back_after_the_unit_of_work_rolls_back(
    test_domain,
):
    store = test_domain.event_store
    identifier = str(uuid4())
    user = User(id=identifier, name="Jane")
    user.raise_(Registered(id=identifier, name="Jane"))
    event = user._events[0]

    with pytest.raises(RuntimeError, match="abort"):
        with UnitOfWork():
            store.append(event)
            raise RuntimeError("abort")

    messages = store.read(f"{User.meta_.stream_category}-{identifier}")
    assert [(m.metadata.headers.type, m.data["name"]) for m in messages] == [
        (Registered.__type__, "Jane")
    ]
