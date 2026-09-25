"""The ``add_``/``remove_`` helpers of a reserved association during replay.

Removing a ``HasMany`` from an event-sourced aggregate and reserving its name
must let a retained ``@apply`` handler that calls ``add_<name>`` or
``remove_<name>`` still replay. During replay those calls do nothing and return
``None``. On the live ``raise_`` path they still raise, and so do
``get_one_from_<name>``, ``filter_<name>`` and a helper for a name that is
neither a field nor reserved.
"""

import copy
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.domain import Domain
from protean.fields import HasMany, Identifier, String
from protean.ir.builder import IRBuilder
from protean.ir.diff import classify_changes, diff_ir


class CartOpened(BaseEvent):
    cart_id: Identifier(required=True)


class ItemAdded(BaseEvent):
    """A retired event. Its handler still calls ``add_items``, whose ``items``
    association has been removed from the aggregate."""

    cart_id: Identifier(required=True)
    name: String(required=True)


class ItemRemoved(BaseEvent):
    cart_id: Identifier(required=True)
    name: String(required=True)


class ItemLookedUp(BaseEvent):
    cart_id: Identifier(required=True)
    name: String(required=True)


class ItemsFiltered(BaseEvent):
    cart_id: Identifier(required=True)
    name: String(required=True)


class GhostAdded(BaseEvent):
    cart_id: Identifier(required=True)
    name: String(required=True)


class AddOnAdded(BaseEvent):
    cart_id: Identifier(required=True)
    name: String(required=True)


class NestedItemAdded(BaseEvent):
    cart_id: Identifier(required=True)
    name: String(required=True)


class CartItem(BaseEntity):
    name: String(max_length=50)


# Return values of the helper calls made inside the handlers below, so a test
# can check what the call returned during replay.
helper_results: list = []


class Cart(BaseAggregate):
    cart_id: Identifier(identifier=True)

    @apply
    def opened(self, event: CartOpened):
        self.cart_id = event.cart_id

    @apply
    def item_added(self, event: ItemAdded):
        helper_results.append(self.add_items(CartItem(name=event.name)))

    @apply
    def item_removed(self, event: ItemRemoved):
        helper_results.append(self.remove_items(CartItem(name=event.name)))

    @apply
    def item_looked_up(self, event: ItemLookedUp):
        # Reads the removed collection: must still raise during replay.
        self.get_one_from_items(name=event.name)

    @apply
    def items_filtered(self, event: ItemsFiltered):
        # Reads the removed collection: must still raise during replay.
        self.filter_items(name=event.name)

    @apply
    def ghost_added(self, event: GhostAdded):
        # ``ghosts`` is neither a field nor reserved: a typo in a retained
        # handler. Replay must still raise on it.
        self.add_ghosts(CartItem(name=event.name))

    @apply
    def add_on_added(self, event: AddOnAdded):
        # The reserved name ``add_on`` itself starts with ``add_``.
        helper_results.append(self.add_add_on(CartItem(name=event.name)))

    @apply
    def nested_item_added(self, event: NestedItemAdded):
        # Applies another event from inside this handler, then calls a
        # reserved helper. Replay mode must still hold for that call.
        self._apply(ItemRemoved(cart_id=event.cart_id, name=event.name))
        helper_results.append(self.add_items(CartItem(name=event.name)))


class LiveCart(BaseAggregate):
    """A cart that still has its ``items`` association."""

    cart_id: Identifier(identifier=True)
    items = HasMany(CartItem)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Cart, event_sourced=True, reserved=["items", "add_on"])
    for event_cls in (
        CartOpened,
        ItemAdded,
        ItemRemoved,
        ItemLookedUp,
        ItemsFiltered,
        GhostAdded,
        AddOnAdded,
        NestedItemAdded,
    ):
        test_domain.register(event_cls, part_of=Cart)
    test_domain.register(LiveCart, event_sourced=True)
    test_domain.register(CartItem, part_of=LiveCart)
    test_domain.init(traverse=False)
    helper_results.clear()


def _opened():
    return CartOpened(cart_id=str(uuid4()))


def test_replay_drops_add_and_remove_helper_calls_on_a_reserved_name():
    opened = _opened()
    added = ItemAdded(cart_id=opened.cart_id, name="pen")
    removed = ItemRemoved(cart_id=opened.cart_id, name="pen")

    cart = Cart.from_events([opened, added, removed])

    assert cart.cart_id == opened.cart_id
    assert cart._version == 2
    # Both helper calls ran and returned None.
    assert helper_results == [None, None]
    # No child entity was rebuilt for the removed association.
    assert "items" not in cart.to_dict()
    assert cart._replaying is False


def test_a_reserved_name_that_starts_with_add_is_matched_exactly():
    opened = _opened()
    cart = Cart.from_events(
        [opened, AddOnAdded(cart_id=opened.cart_id, name="gift wrap")]
    )

    assert helper_results == [None]
    assert cart._version == 1

    # The reserved name itself is not a helper, so reading it still raises.
    cart._replaying = True
    try:
        with pytest.raises(AttributeError, match="add_on"):
            cart.add_on
    finally:
        cart._replaying = False


def test_apply_on_a_live_aggregate_also_drops_helper_calls():
    """Snapshot catch-up calls ``_apply`` on an aggregate that is already
    built, with invariant checks on. This calls ``_apply`` the same way on an
    aggregate from ``from_events``. The helper drop is keyed on the replay
    flag, so it still applies."""
    opened = _opened()
    cart = Cart.from_events([opened])
    assert cart._disable_invariant_checks is False

    cart._apply(ItemAdded(cart_id=opened.cart_id, name="caught up"))

    assert helper_results == [None]
    assert cart._version == 1
    assert cart._replaying is False


def test_live_path_still_raises_on_a_removed_association_helper():
    opened = _opened()
    cart = Cart.from_events([opened])

    with pytest.raises(AttributeError, match="has no attribute 'add_items'"):
        cart.raise_(ItemAdded(cart_id=opened.cart_id, name="live"))

    with pytest.raises(AttributeError, match="has no attribute 'add_items'"):
        cart.add_items(CartItem(name="direct"))

    with pytest.raises(AttributeError, match="has no attribute 'remove_items'"):
        cart.remove_items(CartItem(name="direct"))


def test_replay_still_raises_on_a_helper_for_a_name_neither_field_nor_reserved():
    opened = _opened()

    with pytest.raises(AttributeError, match="has no attribute 'add_ghosts'"):
        Cart.from_events([opened, GhostAdded(cart_id=opened.cart_id, name="boo")])


@pytest.mark.parametrize(
    "name",
    ["add_itemsx", "remove_items_old", "add_item", "add_xitems", "add_", "remove_"],
)
def test_replay_still_raises_on_a_near_miss_of_a_reserved_name(name):
    """Only an exact reserved name after the prefix is dropped. A typo in a
    retained handler still fails replay."""
    cart = Cart.from_events([_opened()])

    cart._replaying = True
    try:
        with pytest.raises(AttributeError, match=f"has no attribute '{name}'"):
            getattr(cart, name)
    finally:
        cart._replaying = False


def test_a_nested_apply_does_not_end_replay_mode_for_the_outer_handler():
    opened = _opened()
    cart = Cart.from_events(
        [opened, NestedItemAdded(cart_id=opened.cart_id, name="pen")]
    )

    # The inner ``remove_items`` and the outer ``add_items`` were both dropped.
    assert helper_results == [None, None]
    assert cart._replaying is False


def test_replay_still_raises_on_get_one_from_a_reserved_name():
    opened = _opened()

    with pytest.raises(AttributeError, match="has no attribute 'get_one_from_items'"):
        Cart.from_events([opened, ItemLookedUp(cart_id=opened.cart_id, name="pen")])


def test_replay_still_raises_on_filter_a_reserved_name():
    opened = _opened()

    with pytest.raises(AttributeError, match="has no attribute 'filter_items'"):
        Cart.from_events([opened, ItemsFiltered(cart_id=opened.cart_id, name="pen")])


def test_replaying_flag_is_reset_when_a_helper_raises_mid_apply():
    opened = _opened()
    cart = Cart.from_events([opened])

    with pytest.raises(AttributeError):
        cart._apply(GhostAdded(cart_id=opened.cart_id, name="boo"))

    assert cart._replaying is False
    # Back on the live path, the reserved helper raises again.
    with pytest.raises(AttributeError, match="has no attribute 'add_items'"):
        cart.add_items(CartItem(name="after"))


def test_live_association_helpers_are_untouched_during_replay():
    """A real ``HasMany`` binds its helpers on the instance, so normal lookup
    finds them and the reserved drop never sees them."""
    cart = LiveCart(cart_id=str(uuid4()))

    cart._replaying = True
    try:
        cart.add_items(CartItem(name="pen"))
    finally:
        cart._replaying = False

    assert [item.name for item in cart.items] == ["pen"]


def test_unknown_attribute_on_a_half_built_aggregate_raises_attribute_error():
    """Before Pydantic's private storage exists, an unknown attribute still
    raises ``AttributeError`` instead of recursing."""
    cart = Cart.__new__(Cart)

    with pytest.raises(AttributeError):
        cart.add_items


def test_deepcopy_of_an_aggregate_with_reserved_names_works():
    opened = _opened()
    cart = Cart.from_events([opened, ItemAdded(cart_id=opened.cart_id, name="pen")])

    copied = copy.deepcopy(cart)

    assert copied.cart_id == cart.cart_id
    with pytest.raises(AttributeError, match="has no attribute 'add_items'"):
        copied.add_items(CartItem(name="pen"))


def _basket_domain(with_items: bool):
    """Build one version of a basket domain.

    ``with_items=True`` is the model before the change: ``Basket`` has a
    ``HasMany`` ``items``. ``with_items=False`` is the model after it: the field
    is removed and its name reserved, while the handler for ``BasketItemAdded``
    is kept and still calls ``add_items``.
    """
    domain = Domain(name="Shop", root_path=".")
    options = {"event_sourced": True}
    if not with_items:
        options["reserved"] = ["items"]

    @domain.event(part_of="Basket")
    class BasketOpened:
        basket_id = Identifier(required=True)

    @domain.event(part_of="Basket")
    class BasketItemAdded:
        basket_id = Identifier(required=True)
        name = String(required=True)

    @domain.entity(part_of="Basket")
    class BasketItem:
        name = String()

    @domain.aggregate(**options)
    class Basket:
        basket_id = Identifier(identifier=True)
        if with_items:
            items = HasMany(BasketItem)

        @apply
        def opened(self, event: BasketOpened):
            self.basket_id = event.basket_id

        @apply
        def item_added(self, event: BasketItemAdded):
            self.add_items(BasketItem(name=event.name))

    domain.init(traverse=False)
    return domain, Basket, BasketOpened, BasketItemAdded


def test_removing_a_reserved_has_many_is_safe_and_old_streams_still_load():
    before, basket_before, opened_cls, added_cls = _basket_domain(with_items=True)
    after, basket_after, _, _ = _basket_domain(with_items=False)

    # The diff reports the removal of the reserved HasMany as safe.
    left_ir = IRBuilder(before).build()
    right_ir = IRBuilder(after).build()
    report = classify_changes(diff_ir(left_ir, right_ir), left_ir, right_ir)

    assert report.is_breaking is False
    assert [
        (change.change_type, change.field_name, change.mitigated_by)
        for change in report.safe_changes
    ] == [("field_removed", "items", "reserved")]

    # A stream written by the old model, with an item added.
    basket_id = str(uuid4())
    with before.domain_context():
        basket = basket_before(basket_id=basket_id)
        basket.raise_(opened_cls(basket_id=basket_id))
        basket.raise_(added_cls(basket_id=basket_id, name="pen"))
        assert [item.name for item in basket.items] == ["pen"]
        before.repository_for(basket_before).add(basket)
        messages = before.event_store.store._read("$all")

    assert [message["type"] for message in messages] == [
        "Shop.BasketOpened.v1",
        "Shop.BasketItemAdded.v1",
    ]

    # The new model loads that stream through its event store.
    with after.domain_context():
        for message in messages:
            after.event_store.store._write(
                message["stream_name"],
                message["type"],
                message["data"],
                message["metadata"],
            )
        loaded = after.repository_for(basket_after).get(basket_id)

    assert loaded.basket_id == basket_id
    assert loaded._version == 1
    # The item added through the removed association is not rebuilt.
    assert "items" not in loaded.to_dict()
