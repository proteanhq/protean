"""Category and ``$all`` reads page by ``global_position`` (inclusive), and do so
consistently across adapters.

Regression for a multi-stream category, where a stream's own ordinal diverges
from ``global_position``: the memory store used to filter/order category and
``$all`` reads by the per-stream ``position``, so once a category held more than
one stream a subscription paging by ``global_position`` silently read the wrong
batch (often nothing). MessageDB keyed category reads on ``global_position`` but
read ``$all`` with a strict, unordered ``> position``. Both now agree: inclusive,
``global_position``-ordered.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.fields import Identifier, String


class Registered(BaseEvent):
    id = Identifier()
    email = String()


class Activated(BaseEvent):
    id = Identifier(required=True)


class Renamed(BaseEvent):
    id = Identifier(required=True)
    name = String(required=True, max_length=50)


class User(BaseAggregate):
    email = String()
    name = String(max_length=50)

    @apply
    def on_registered(self, event: Registered):
        self.id = event.id
        self.email = event.email

    @apply
    def on_activated(self, event: Activated):
        pass

    @apply
    def on_renamed(self, event: Renamed):
        self.name = event.name


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Activated, part_of=User)
    test_domain.register(Renamed, part_of=User)
    test_domain.init(traverse=False)


def _append(test_domain, user, event):
    user.raise_(event)
    test_domain.event_store.store.append(user._events[-1])


@pytest.fixture
def multi_stream_category(test_domain):
    """Populate one category (``test::user``) with two streams whose per-stream
    ordinals deliberately diverge from ``global_position``: three events on the
    first user, then one on a second. Ordered by stream position that is
    ``[user_a:0, user_b:0, user_a:1, user_a:2]``; ordered by ``global_position``
    it is ``[a:0, a:1, a:2, b:0]`` — the two orders differ, so a wrong sort key
    is observable."""
    id_a, id_b = str(uuid4()), str(uuid4())

    user_a = User(id=id_a, email="a@example.com")
    _append(test_domain, user_a, Registered(id=id_a, email="a@example.com"))
    _append(test_domain, user_a, Activated(id=id_a))
    _append(test_domain, user_a, Renamed(id=id_a, name="A"))

    user_b = User(id=id_b, email="b@example.com")
    _append(test_domain, user_b, Registered(id=id_b, email="b@example.com"))

    return id_a, id_b


def _global_positions(messages):
    return [m.metadata.event_store.global_position for m in messages]


@pytest.mark.eventstore
def test_category_read_is_global_position_ordered(test_domain, multi_stream_category):
    messages = test_domain.event_store.store.read("test::user")

    gpos = _global_positions(messages)
    assert len(gpos) == 4
    assert gpos == sorted(gpos)  # global order, not the per-stream ordinal
    assert len(set(gpos)) == 4  # nothing dropped or duplicated


@pytest.mark.eventstore
def test_category_read_is_inclusive_of_position(test_domain, multi_stream_category):
    store = test_domain.event_store.store
    gpos = _global_positions(store.read("test::user"))

    # Paging from the third global position returns exactly it and everything
    # after — the per-stream sort key would have returned nothing here (no stream
    # has an ordinal that high).
    page = store.read("test::user", position=gpos[2])
    assert _global_positions(page) == gpos[2:]


@pytest.mark.eventstore
def test_all_read_is_global_position_ordered(test_domain, multi_stream_category):
    messages = test_domain.event_store.store.read("$all")

    gpos = _global_positions(messages)
    assert len(gpos) == 4
    assert gpos == sorted(gpos)
    assert len(set(gpos)) == 4


@pytest.mark.eventstore
def test_all_read_is_inclusive_of_position(test_domain, multi_stream_category):
    store = test_domain.event_store.store
    gpos = _global_positions(store.read("$all"))

    page = store.read("$all", position=gpos[1])
    assert _global_positions(page) == gpos[1:]


@pytest.mark.eventstore
def test_specific_stream_read_pages_by_stream_position(
    test_domain, multi_stream_category
):
    """A specific stream (``category-id``) still pages by its per-stream ordinal,
    not global_position — guard for the specific-stream branch."""
    id_a, _ = multi_stream_category
    stream = f"test::user-{id_a}"
    store = test_domain.event_store.store

    # user_a has three events at per-stream positions 0, 1, 2. Reading from
    # per-stream position 1 returns this stream's last two events. Keyed on
    # global_position this would instead return everything at global_position >= 1
    # (all four events, including the other stream's).
    page = store.read(stream, position=1)
    assert len(page) == 2
    assert all(m.metadata.headers.stream == stream for m in page)
