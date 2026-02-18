"""Regression tests for the raise_() → @apply integration.

Validates the core ES invariant: raise_() calls @apply handlers so they
are the single source of truth for state mutations. Also tests
_create_for_reconstitution(), _create_new(), and the simplified from_events().
"""

from enum import Enum
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.value_object import BaseValueObject
from protean.fields import Float, HasMany, Identifier, String, ValueObject


# ---------------------------------------------------------------------------
# Test aggregates
# ---------------------------------------------------------------------------
class UserStatus(Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class UserRegistered(BaseEvent):
    user_id: Identifier(required=True)
    name: String(max_length=50, required=True)
    email: String(required=True)


class UserActivated(BaseEvent):
    user_id: Identifier(required=True)


class UserRenamed(BaseEvent):
    user_id: Identifier(required=True)
    name: String(required=True, max_length=50)


class User(BaseAggregate):
    user_id: Identifier(identifier=True)
    name: String(max_length=50, required=True)
    email: String(required=True)
    status: String(choices=UserStatus)

    @classmethod
    def register(cls, user_id, name, email):
        user = cls._create_new(user_id=user_id)
        user.raise_(UserRegistered(user_id=user_id, name=name, email=email))
        return user

    def activate(self):
        self.raise_(UserActivated(user_id=self.user_id))

    def change_name(self, name):
        self.raise_(UserRenamed(user_id=self.user_id, name=name))

    @apply
    def registered(self, event: UserRegistered):
        self.user_id = event.user_id
        self.name = event.name
        self.email = event.email
        self.status = UserStatus.INACTIVE.value

    @apply
    def activated(self, event: UserActivated):
        self.status = UserStatus.ACTIVE.value

    @apply
    def renamed(self, event: UserRenamed):
        self.name = event.name


# Aggregate with event shape != constructor shape (no matching required fields)
class AccountOpened(BaseEvent):
    account_number: String(required=True)
    holder_name: String(required=True)
    initial_balance: Float(required=True)


class DepositMade(BaseEvent):
    account_number: String(required=True)
    amount: Float(required=True)


class Account(BaseAggregate):
    account_number: String(identifier=True)
    holder_name: String(required=True)
    balance: Float(default=0.0)

    @classmethod
    def open(cls, account_number, holder_name, initial_balance):
        account = cls._create_new(account_number=account_number)
        account.raise_(
            AccountOpened(
                account_number=account_number,
                holder_name=holder_name,
                initial_balance=initial_balance,
            )
        )
        return account

    def deposit(self, amount):
        self.raise_(DepositMade(account_number=self.account_number, amount=amount))

    @apply
    def on_opened(self, event: AccountOpened):
        self.account_number = event.account_number
        self.holder_name = event.holder_name
        self.balance = event.initial_balance

    @apply
    def on_deposit(self, event: DepositMade):
        self.balance = (self.balance or 0.0) + event.amount


# Aggregate with ValueObject field (for VO shadow field reconstitution coverage)
class Address(BaseValueObject):
    street: String(max_length=100)
    city: String(max_length=50)


class PersonCreated(BaseEvent):
    person_id: Identifier(required=True)
    name: String(required=True)
    street: String()
    city: String()


class Person(BaseAggregate):
    person_id: Identifier(identifier=True)
    name: String(required=True)
    address: ValueObject(Address)

    @classmethod
    def create(cls, person_id, name, street=None, city=None):
        person = cls._create_new(person_id=person_id)
        person.raise_(
            PersonCreated(person_id=person_id, name=name, street=street, city=city)
        )
        return person

    @apply
    def on_created(self, event: PersonCreated):
        self.person_id = event.person_id
        self.name = event.name
        if event.street and event.city:
            self.address = Address(street=event.street, city=event.city)


# Aggregate with HasMany field (for association reconstitution coverage)
class LineItem(BaseEntity):
    product_name: String(max_length=100)
    quantity: Float(default=1.0)


class OrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
    customer: String(required=True)


class ItemAdded(BaseEvent):
    order_id: Identifier(required=True)
    product_name: String(required=True)
    quantity: Float(required=True)


class Order(BaseAggregate):
    order_id: Identifier(identifier=True)
    customer: String(required=True)
    items: HasMany(LineItem)

    @classmethod
    def place(cls, order_id, customer):
        order = cls._create_new(order_id=order_id)
        order.raise_(OrderPlaced(order_id=order_id, customer=customer))
        return order

    def add_item(self, product_name, quantity):
        self.raise_(
            ItemAdded(
                order_id=self.order_id,
                product_name=product_name,
                quantity=quantity,
            )
        )

    @apply
    def on_placed(self, event: OrderPlaced):
        self.order_id = event.order_id
        self.customer = event.customer

    @apply
    def on_item_added(self, event: ItemAdded):
        self.add_items(
            LineItem(product_name=event.product_name, quantity=event.quantity)
        )


# Aggregate with two @apply handlers for the same event (for double-increment test)
class ItemCreated(BaseEvent):
    item_id: Identifier(required=True)
    name: String(required=True)


class Item(BaseAggregate):
    item_id: Identifier(identifier=True)
    name: String(required=True)
    audit_log: String(default="")

    @apply
    def on_created_set_fields(self, event: ItemCreated):
        self.item_id = event.item_id
        self.name = event.name

    @apply
    def on_created_set_audit(self, event: ItemCreated):
        self.audit_log = f"created:{event.name}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(UserActivated, part_of=User)
    test_domain.register(UserRenamed, part_of=User)
    test_domain.register(Account, is_event_sourced=True)
    test_domain.register(AccountOpened, part_of=Account)
    test_domain.register(DepositMade, part_of=Account)
    test_domain.register(Item, is_event_sourced=True)
    test_domain.register(ItemCreated, part_of=Item)
    test_domain.register(Person, is_event_sourced=True)
    test_domain.register(PersonCreated, part_of=Person)
    test_domain.register(Order, is_event_sourced=True)
    test_domain.register(LineItem, part_of=Order)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(ItemAdded, part_of=Order)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Test: raise_() applies state immediately for ES aggregates
# ---------------------------------------------------------------------------
class TestRaiseAppliesState:
    def test_raise_applies_state_immediately(self):
        """After raise_(), the aggregate's in-memory state reflects
        the @apply handler — not just whatever the business method set."""
        user = User.register(user_id=str(uuid4()), name="John", email="j@example.com")
        assert user.name == "John"
        assert user.email == "j@example.com"
        assert user.status == UserStatus.INACTIVE.value

    def test_raise_applies_subsequent_events(self):
        """Subsequent raise_() calls also apply handlers."""
        user = User.register(user_id=str(uuid4()), name="John", email="j@example.com")
        user.activate()
        assert user.status == UserStatus.ACTIVE.value

        user.change_name("Jane")
        assert user.name == "Jane"

    def test_create_new_produces_valid_aggregate(self):
        """_create_new() yields an aggregate with identity but no other state."""
        uid = str(uuid4())
        user = User._create_new(user_id=uid)
        assert user.user_id == uid
        assert user.name is None  # Not yet set — no event applied


# ---------------------------------------------------------------------------
# Test: live vs replay state equivalence
# ---------------------------------------------------------------------------
class TestLiveReplayEquivalence:
    def test_live_and_replay_produce_identical_state(self):
        """Aggregate created via factory must match one reconstructed
        from the same events via from_events()."""
        live = User.register(user_id=str(uuid4()), name="John", email="j@example.com")
        live.activate()
        live.change_name("Jane")

        replayed = User.from_events(live._events)

        assert replayed.user_id == live.user_id
        assert replayed.name == live.name
        assert replayed.email == live.email
        assert replayed.status == live.status
        assert replayed._version == live._version

    def test_equivalence_with_single_event(self):
        """Works even with just the creation event."""
        live = User.register(
            user_id=str(uuid4()), name="Alice", email="alice@example.com"
        )

        replayed = User.from_events(live._events)

        assert replayed.user_id == live.user_id
        assert replayed.name == live.name
        assert replayed.status == live.status


# ---------------------------------------------------------------------------
# Test: from_events() works without constructor constraint
# ---------------------------------------------------------------------------
class TestFromEventsDecoupled:
    def test_from_events_does_not_require_matching_constructor(self):
        """First event can have fields that don't match aggregate's
        required constructor parameters. AccountOpened has initial_balance
        but Account's constructor requires holder_name — from_events()
        bypasses the constructor entirely."""
        account = Account.open("ACC-001", "Alice", 1000.0)

        # Reconstruct purely from events
        replayed = Account.from_events(account._events)

        assert replayed.account_number == "ACC-001"
        assert replayed.holder_name == "Alice"
        assert replayed.balance == 1000.0

    def test_from_events_handles_multiple_events(self):
        """Reconstruction handles creation + subsequent events."""
        account = Account.open("ACC-002", "Bob", 500.0)
        account.deposit(250.0)
        account.deposit(100.0)

        replayed = Account.from_events(account._events)

        assert replayed.balance == 850.0
        assert replayed._version == 2  # 3 events → versions 0, 1, 2


# ---------------------------------------------------------------------------
# Test: version increments once per event, not per projection
# ---------------------------------------------------------------------------
class TestVersionPerEvent:
    def test_version_increments_once_per_event_not_per_projection(self):
        """Regression: old _apply() had version++ inside the for-loop
        over projection functions, which would double-increment if an
        event had two handlers registered.

        The Item aggregate has TWO @apply handlers for ItemCreated.
        After applying one event via from_events, _version must be 0
        (not 1, which would happen with double-increment)."""
        item_id = str(uuid4())
        event = ItemCreated(item_id=item_id, name="Widget")

        # Apply single event via from_events
        item = Item.from_events([event])

        assert item.name == "Widget"
        assert item.audit_log == "created:Widget"
        assert item._version == 0  # One event → version 0

    def test_version_correct_after_raise(self):
        """Version is also correct on the live path via raise_()."""
        item = Item._create_new(item_id=str(uuid4()))
        item.raise_(ItemCreated(item_id=str(item.item_id), name="Gadget"))

        # raise_() increments version once
        assert item._version == 0

    def test_version_correct_through_multiple_events(self):
        """Version tracks correctly through multiple events."""
        user = User.register(user_id=str(uuid4()), name="John", email="j@example.com")
        assert user._version == 0

        user.activate()
        assert user._version == 1

        user.change_name("Jane")
        assert user._version == 2

        # Replay should produce same version
        replayed = User.from_events(user._events)
        assert replayed._version == 2


# ---------------------------------------------------------------------------
# Test: event store round-trip
# ---------------------------------------------------------------------------
class TestEventStoreRoundTrip:
    @pytest.mark.eventstore
    def test_create_persist_reload_produces_identical_state(self, test_domain):
        """Create → persist → reload produces identical aggregate state."""
        user = User.register(user_id=str(uuid4()), name="John", email="j@example.com")
        user.activate()
        user.change_name("Jane")

        test_domain.repository_for(User).add(user)

        loaded = test_domain.repository_for(User).get(user.user_id)

        assert loaded.user_id == user.user_id
        assert loaded.name == user.name
        assert loaded.email == user.email
        assert loaded.status == user.status
        assert loaded._version == user._version


# ---------------------------------------------------------------------------
# Test: _create_new() with auto-generated identity
# ---------------------------------------------------------------------------
class TestCreateNewAutoIdentity:
    def test_auto_generates_identity_when_not_provided(self):
        """_create_new() without identity kwargs auto-generates an ID."""
        user = User._create_new()
        assert user.user_id is not None
        assert isinstance(user.user_id, str)
        assert len(user.user_id) > 0

    def test_auto_identity_is_unique_each_call(self):
        """Each _create_new() call generates a unique identity."""
        u1 = User._create_new()
        u2 = User._create_new()
        assert u1.user_id != u2.user_id

    def test_auto_identity_can_raise_events(self):
        """Auto-generated identity works with subsequent raise_()."""
        user = User._create_new()
        uid = user.user_id
        user.raise_(UserRegistered(user_id=uid, name="Auto", email="auto@test.com"))
        assert user.name == "Auto"
        assert user.user_id == uid


# ---------------------------------------------------------------------------
# Test: reconstitution with ValueObject fields
# ---------------------------------------------------------------------------
class TestReconstitutionWithValueObject:
    def test_create_for_reconstitution_initializes_vo_shadow_fields(self):
        """_create_for_reconstitution sets VO shadow fields to None."""
        person = Person._create_for_reconstitution()
        # VO shadow fields (address_street, address_city) should be None
        assert person.address is None

    def test_from_events_with_value_object(self):
        """from_events correctly reconstructs aggregates with VO fields."""
        person = Person.create("P-001", "Alice", street="123 Main", city="Springfield")

        replayed = Person.from_events(person._events)
        assert replayed.person_id == "P-001"
        assert replayed.name == "Alice"
        assert replayed.address is not None
        assert replayed.address.street == "123 Main"
        assert replayed.address.city == "Springfield"

    def test_from_events_with_none_value_object(self):
        """from_events handles None VO fields gracefully."""
        person = Person.create("P-002", "Bob")

        replayed = Person.from_events(person._events)
        assert replayed.name == "Bob"
        assert replayed.address is None


# ---------------------------------------------------------------------------
# Test: reconstitution with HasMany fields
# ---------------------------------------------------------------------------
class TestReconstitutionWithHasMany:
    def test_create_for_reconstitution_sets_up_association_methods(self):
        """_create_for_reconstitution creates add_*/remove_* pseudo-methods."""
        order = Order._create_for_reconstitution()
        assert hasattr(order, "add_items")
        assert hasattr(order, "remove_items")
        assert hasattr(order, "get_one_from_items")
        assert hasattr(order, "filter_items")

    def test_raise_with_has_many_child_entities(self):
        """raise_() + @apply can add child entities via HasMany."""
        order = Order.place("ORD-001", "Alice")
        order.add_item("Widget", 3.0)
        order.add_item("Gadget", 1.0)

        assert order.customer == "Alice"
        assert len(order.items) == 2
        assert order.items[0].product_name == "Widget"
        assert order.items[1].product_name == "Gadget"

    def test_from_events_with_has_many(self):
        """from_events correctly replays events that add child entities."""
        order = Order.place("ORD-002", "Bob")
        order.add_item("Widget", 2.0)

        replayed = Order.from_events(order._events)
        assert replayed.customer == "Bob"
        assert len(replayed.items) == 1
        assert replayed.items[0].product_name == "Widget"
        assert replayed.items[0].quantity == 2.0


# ---------------------------------------------------------------------------
# Test: backward compatibility with dual-mutation pattern
# ---------------------------------------------------------------------------
class TestBackwardCompatibility:
    def test_dual_mutation_pattern_still_works(self):
        """Existing code that mutates state directly AND raises events
        continues to work. The @apply handler overwrites the direct mutation
        with identical values, so the final state is correct."""
        uid = str(uuid4())
        user = User(user_id=uid, name="Initial", email="init@test.com")
        # Direct mutation + raise_ (the old pattern)
        user.name = "Direct"
        user.raise_(UserRenamed(user_id=uid, name="Direct"))

        # @apply handler overwrites name with event.name = "Direct"
        assert user.name == "Direct"

    def test_non_es_aggregate_unaffected(self, test_domain):
        """Non-ES aggregates do not invoke @apply on raise_()."""

        class SimpleEvent(BaseEvent):
            msg: String()

        class Simple(BaseAggregate):
            msg: String()

        test_domain.register(Simple)
        test_domain.register(SimpleEvent, part_of=Simple)
        test_domain.init(traverse=False)

        s = Simple(msg="hello")
        s.raise_(SimpleEvent(msg="world"))

        # Non-ES: raise_ only appends the event, no @apply call
        assert s.msg == "hello"  # Not overwritten
        assert len(s._events) == 1


# ---------------------------------------------------------------------------
# Test: missing @apply handler raises NotImplementedError
# ---------------------------------------------------------------------------
class TestMissingApplyHandler:
    def test_raise_without_handler_raises_error(self, test_domain):
        """Raising an event with no @apply handler is an error for ES aggregates."""

        class OrphanEvent(BaseEvent):
            data: String()

        class Orphan(BaseAggregate):
            data: String()

        test_domain.register(Orphan, is_event_sourced=True)
        test_domain.register(OrphanEvent, part_of=Orphan)
        test_domain.init(traverse=False)

        orphan = Orphan(data="test")
        with pytest.raises(NotImplementedError, match="No handler registered"):
            orphan.raise_(OrphanEvent(data="boom"))


# ---------------------------------------------------------------------------
# Test: fact events are excluded from @apply
# ---------------------------------------------------------------------------
class TestFactEventExclusion:
    def test_fact_events_do_not_trigger_apply(self):
        """Fact events (auto-generated state snapshots) are excluded
        from @apply because they have no handlers."""
        user = User.register(user_id=str(uuid4()), name="John", email="j@example.com")
        # Fact events end with "FactEvent" in name — they are auto-generated
        # by the framework and should not look for @apply handlers.
        # This is tested implicitly: if fact events tried @apply, they'd
        # get NotImplementedError since no handler exists for them.
        assert len(user._events) == 1  # Only the UserRegistered event
