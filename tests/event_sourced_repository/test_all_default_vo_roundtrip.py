"""An event-sourced aggregate whose ``@apply`` sets an embedded VO to
all-default (falsy) values must reload as that VO, not ``None``.

Reconstitution replays events through ``@apply``; the handler assigns
``self.levels = StockLevels(...)``, which hits ``ValueObject.__set__``. The
truthiness gate there used to reset an all-default VO to ``None``, so the VO
vanished on reload while a VO with any non-default field survived.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.value_object import BaseValueObject
from protean.domain import Domain
from protean.fields import Identifier, Integer, ValueObject
from tests.shared import MESSAGE_DB_URI


class StockLevels(BaseValueObject):
    on_hand = Integer(default=0)
    reserved = Integer(default=0)
    available = Integer(default=0)


class StockInitialized(BaseEvent):
    item_id = Identifier(required=True)
    initial_quantity = Integer(required=True)


class InventoryItem(BaseAggregate):
    item_id = Identifier(identifier=True)
    levels = ValueObject(StockLevels)

    @classmethod
    def initialize(cls, item_id, initial_quantity):
        item = cls(item_id=item_id)
        item.raise_(
            StockInitialized(item_id=item_id, initial_quantity=initial_quantity)
        )
        return item

    @apply
    def on_initialized(self, event: StockInitialized):
        self.item_id = event.item_id
        self.levels = StockLevels(
            on_hand=event.initial_quantity,
            reserved=0,
            available=event.initial_quantity,
        )


def _round_trip(domain, initial_quantity):
    item = InventoryItem.initialize(
        item_id=str(uuid4()), initial_quantity=initial_quantity
    )
    domain.repository_for(InventoryItem).add(item)
    return domain.repository_for(InventoryItem).get(item.item_id)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    # ``no_test_domain`` classes (the Message-DB variant) get ``None`` here and
    # build their own domain.
    if test_domain is None:
        return
    test_domain.register(InventoryItem, is_event_sourced=True)
    test_domain.register(StockInitialized, part_of=InventoryItem)
    test_domain.init(traverse=False)


class TestAllDefaultValueObjectRoundTrip:
    def test_all_default_vo_reloads_as_equal_vo(self, test_domain):
        # initial_quantity=0 -> every StockLevels field is its 0 default.
        reloaded = _round_trip(test_domain, initial_quantity=0)

        # Before the fix this was ``None``.
        assert reloaded.levels is not None
        assert reloaded.levels == StockLevels(on_hand=0, reserved=0, available=0)

    def test_non_default_vo_reloads_as_equal_vo(self, test_domain):
        # Positive control: a VO with non-default fields always round-tripped.
        reloaded = _round_trip(test_domain, initial_quantity=5)

        assert reloaded.levels == StockLevels(on_hand=5, reserved=0, available=5)


def _make_messagedb_domain():
    """An event-sourced domain backed by a real Message-DB event store."""
    domain = Domain(name="InventoryMDB")
    domain.config["event_store"] = {
        "provider": "message_db",
        "database_uri": MESSAGE_DB_URI,
    }
    domain.register(InventoryItem, is_event_sourced=True)
    domain.register(StockInitialized, part_of=InventoryItem)
    domain.init(traverse=False)
    return domain


@pytest.mark.message_db
@pytest.mark.no_test_domain
class TestAllDefaultValueObjectRoundTripOnMessageDB:
    """The issue reproduces on Message-DB too — the fix is in the VO
    materialization path, so it holds end-to-end against the real store."""

    @pytest.fixture
    def domain(self):
        domain = _make_messagedb_domain()
        with domain.domain_context():
            store = domain.event_store.store
            store._data_reset()
            yield domain
            # ``no_test_domain`` skips ``run_around_tests``, so reset + close the
            # store here to keep the shared instance clean and avoid pool leaks.
            store._data_reset()
            store.close()

    def test_all_default_vo_reloads_as_equal_vo(self, domain):
        reloaded = _round_trip(domain, initial_quantity=0)

        assert reloaded.levels is not None
        assert reloaded.levels == StockLevels(on_hand=0, reserved=0, available=0)
