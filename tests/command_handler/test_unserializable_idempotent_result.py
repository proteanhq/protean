"""A keyed command whose handler returns a value ``json.dumps`` rejects.

The idempotency store cannot record the result, so it logs a warning and the
command's work stands. Requires a running Redis and the ``--redis`` flag.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Identifier, String
from protean.utils import Processing
from protean.utils.globals import current_domain
from protean.utils.mixins import handle
from tests.shared import REDIS_URI

REDIS_IDEMPOTENCY_URL = f"{REDIS_URI}/5"

pytestmark = pytest.mark.redis

runs: list[str] = []
handled_events: list[str] = []


class Tagged(BaseEvent):
    item_id: Identifier(required=True)


class Item(BaseAggregate):
    name: String(max_length=50)


class TagItem(BaseCommand):
    item_id: Identifier(identifier=True)


class ItemHandlers(BaseCommandHandler):
    @handle(TagItem)
    def tag(self, command: TagItem) -> set[str]:
        runs.append(command.item_id)
        item = Item(id=command.item_id, name="tagged")
        item.raise_(Tagged(item_id=command.item_id))
        current_domain.repository_for(Item).add(item)
        return {command.item_id}


class ItemEvents(BaseEventHandler):
    @handle(Tagged)
    def on_tagged(self, event: Tagged) -> None:
        handled_events.append(event.item_id)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    runs.clear()
    handled_events.clear()
    test_domain.config["idempotency"]["redis_url"] = REDIS_IDEMPOTENCY_URL
    # Reset the lazily-initialized store so it picks up the new config
    test_domain._idempotency_store = None

    test_domain.register(Item)
    test_domain.register(Tagged, part_of=Item)
    test_domain.register(TagItem, part_of=Item)
    test_domain.register(ItemHandlers, part_of=Item)
    test_domain.register(ItemEvents, part_of=Item)
    test_domain.init(traverse=False)

    # An inactive store skips result serialization, so these tests would pass
    # without reaching the failure path.
    assert test_domain.idempotency_store.is_active

    test_domain.idempotency_store.flush()
    yield
    test_domain.idempotency_store.flush()


def test_a_nested_command_does_not_fail_the_outer_commit(test_domain):
    item_id = str(uuid4())
    key = f"tag-{item_id}"
    test_domain.config["event_processing"] = Processing.SYNC.value

    with UnitOfWork():
        test_domain.process(
            TagItem(item_id=item_id), asynchronous=False, idempotency_key=key
        )

    assert test_domain.repository_for(Item).get(item_id).name == "tagged"
    assert test_domain.idempotency_store.check(key) is None
    assert handled_events == [item_id]


def test_a_top_level_command_returns_its_result(test_domain):
    item_id = str(uuid4())
    key = f"tag-{item_id}"

    result = test_domain.process(
        TagItem(item_id=item_id), asynchronous=False, idempotency_key=key
    )

    assert result == {item_id}
    assert test_domain.repository_for(Item).get(item_id).name == "tagged"
    assert test_domain.idempotency_store.check(key) is None


def test_a_retry_with_the_same_key_runs_the_command_again(test_domain):
    # The key alone decides deduplication, so each run tags a new item and
    # the second run does not collide with the first run's saved aggregate.
    item_ids = [str(uuid4()), str(uuid4())]
    key = f"tag-{item_ids[0]}"

    for item_id in item_ids:
        with UnitOfWork():
            test_domain.process(
                TagItem(item_id=item_id), asynchronous=False, idempotency_key=key
            )

    assert runs == item_ids
