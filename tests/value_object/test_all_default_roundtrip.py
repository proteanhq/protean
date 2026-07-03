"""An embedded ValueObject whose every field holds a default/falsy value is
still *present*, not absent. It must survive assignment and serialization
instead of collapsing to ``None`` (#1078).

``BaseValueObject.__bool__`` reports an all-default VO as falsy, so the
``ValueObject`` field's truthiness gates used to reset it to ``None`` on
assignment and drop it from ``to_dict()`` / ``as_dict()``.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.fields import Boolean, Integer, String, ValueObject


class StockLevels(BaseValueObject):
    on_hand = Integer(default=0)
    reserved = Integer(default=0)
    available = Integer(default=0)


class InventoryItem(BaseAggregate):
    sku = String()
    levels = ValueObject(StockLevels)


def test_all_default_vo_is_falsy_but_present():
    """The VO is genuinely falsy — that is why the truthiness gates dropped it."""
    vo = StockLevels(on_hand=0, reserved=0, available=0)
    assert bool(vo) is False
    assert vo is not None


def test_assigning_an_all_default_vo_is_preserved():
    item = InventoryItem(sku="SKU-1", levels=StockLevels(on_hand=0, reserved=0))

    # Before the fix, ``__set__`` saw a falsy VO and reset it to ``None``.
    assert item.levels is not None
    assert item.levels == StockLevels(on_hand=0, reserved=0, available=0)
    # Shadow (flattened) fields carry the zeros, not ``None``.
    assert item.levels_on_hand == 0
    assert item.levels_reserved == 0
    assert item.levels_available == 0


def test_all_default_vo_serializes_in_to_dict():
    item = InventoryItem(sku="SKU-1", levels=StockLevels())

    # Before the fix, ``as_dict`` returned ``None`` and ``to_dict`` dropped the key.
    assert item.to_dict()["levels"] == {
        "on_hand": 0,
        "reserved": 0,
        "available": 0,
    }


def test_never_set_vo_stays_none():
    """Negative control: an unset VO is still absent (``None``), not a zero VO."""
    item = InventoryItem(sku="SKU-1")

    assert item.levels is None
    assert "levels" not in item.to_dict()
    assert item.levels_on_hand is None


def test_all_default_vo_reconstructs_from_shadow_columns():
    """The flattened form reconstructs into an equal VO (repository retrieval)."""
    original = InventoryItem(sku="SKU-1", levels=StockLevels(on_hand=0, reserved=0))

    # Simulate persistence + retrieval: the DAO hands back flattened columns.
    reconstructed = InventoryItem(
        sku=original.sku,
        levels_on_hand=original.levels_on_hand,
        levels_reserved=original.levels_reserved,
        levels_available=original.levels_available,
    )

    assert reconstructed.levels is not None
    assert reconstructed.levels == original.levels


class TestStandardRepositoryRoundTrip:
    """Full add + get through a (non-event-sourced) repository — symmetric with
    the event-sourced round-trip, covering the DAO flatten/reconstruct path."""

    @pytest.fixture(autouse=True)
    def register(self, test_domain):
        test_domain.register(InventoryItem)
        test_domain.init(traverse=False)

    def test_all_default_vo_round_trips_through_repository(self, test_domain):
        item = InventoryItem(sku="SKU-1", levels=StockLevels(on_hand=0, reserved=0))
        test_domain.repository_for(InventoryItem).add(item)

        reloaded = test_domain.repository_for(InventoryItem).get(item.id)

        # Before the fix the flattened shadow columns persisted as NULLs and the
        # VO reconstructed as None.
        assert reloaded.levels is not None
        assert reloaded.levels == StockLevels(on_hand=0, reserved=0, available=0)

    def test_never_set_vo_stays_none_through_repository(self, test_domain):
        item = InventoryItem(sku="SKU-1")
        test_domain.repository_for(InventoryItem).add(item)

        reloaded = test_domain.repository_for(InventoryItem).get(item.id)

        assert reloaded.levels is None


class Flag(BaseValueObject):
    enabled = Boolean(default=False)


class FeatureToggle(BaseAggregate):
    name = String()
    flag = ValueObject(Flag)


class AllNoneVO(BaseValueObject):
    note = String()
    label = String()


class Tag(BaseAggregate):
    name = String()
    meta = ValueObject(AllNoneVO)


class TestFalsyButNonNullFieldsRoundTrip:
    """A single Boolean(default=False) VO — falsy, but the column is ``False``,
    not NULL — must round-trip like the all-zeros case."""

    @pytest.fixture(autouse=True)
    def register(self, test_domain):
        test_domain.register(FeatureToggle)
        test_domain.init(traverse=False)

    def test_boolean_false_vo_round_trips(self, test_domain):
        toggle = FeatureToggle(name="beta", flag=Flag(enabled=False))
        test_domain.repository_for(FeatureToggle).add(toggle)

        reloaded = test_domain.repository_for(FeatureToggle).get(toggle.id)

        assert reloaded.flag is not None
        assert reloaded.flag == Flag(enabled=False)


class TestAllNoneVOBoundary:
    """Boundary of the fix: a VO whose every field defaults to ``None`` has
    only NULL shadow columns, which are byte-identical to "never set." Flattened
    storage cannot tell them apart without a presence marker, so such a VO reads
    back as ``None`` on relational/document retrieval. Pinned so the boundary is
    an intended, documented contract rather than a silent surprise (#1078).
    """

    @pytest.fixture(autouse=True)
    def register(self, test_domain):
        test_domain.register(Tag)
        test_domain.init(traverse=False)

    def test_all_none_vo_is_present_in_memory_before_persist(self, test_domain):
        # In-memory (pre-persistence) the VO is honoured — the fix keeps it.
        tag = Tag(name="t", meta=AllNoneVO(note=None, label=None))
        assert tag.meta is not None
        assert tag.meta == AllNoneVO(note=None, label=None)

    def test_all_none_vo_reads_back_as_none_from_repository(self, test_domain):
        tag = Tag(name="t", meta=AllNoneVO(note=None, label=None))
        test_domain.repository_for(Tag).add(tag)

        reloaded = test_domain.repository_for(Tag).get(tag.id)

        # All-NULL columns are indistinguishable from an unset VO in flattened
        # storage — see the class docstring.
        assert reloaded.meta is None


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestCrossDatabaseRoundTrip:
    """The all-default VO round-trip against real relational providers
    (sqlite / postgresql via ``--db``), not only the in-memory adapter — the
    fix lives in adapter-agnostic core, and this proves it end-to-end (#1078)."""

    @pytest.fixture(autouse=True)
    def register(self, test_domain):
        test_domain.register(InventoryItem)
        test_domain.init(traverse=False)

    def test_all_default_vo_round_trips(self, test_domain):
        item = InventoryItem(sku="SKU-1", levels=StockLevels(on_hand=0, reserved=0))
        test_domain.repository_for(InventoryItem).add(item)

        reloaded = test_domain.repository_for(InventoryItem).get(item.id)

        assert reloaded.levels is not None
        assert reloaded.levels == StockLevels(on_hand=0, reserved=0, available=0)

    def test_never_set_vo_stays_none(self, test_domain):
        item = InventoryItem(sku="SKU-1")
        test_domain.repository_for(InventoryItem).add(item)

        reloaded = test_domain.repository_for(InventoryItem).get(item.id)

        assert reloaded.levels is None
