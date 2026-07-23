"""Generic optimistic locking tests that run against all database providers.

Covers version increment on save, concurrent update detection, version
preservation through persist/retrieve round-trips, and that a change confined
to a child entity still advances the aggregate root's version.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.unit_of_work import UnitOfWork
from protean.core.value_object import BaseValueObject
from protean.exceptions import ExpectedVersionError, ObjectNotFoundError
from protean.fields import HasMany, HasOne, Integer, Reference, String, ValueObject
from protean.utils.globals import current_uow


class Counter(BaseAggregate):
    name: String(max_length=100, required=True)
    value: Integer(default=0)


class Money(BaseValueObject):
    currency: String(max_length=3)
    amount: Integer()


class Order(BaseAggregate):
    label: String(max_length=50, required=False)
    lines = HasMany("OrderLine")


class OrderLine(BaseEntity):
    sku: String(max_length=20, required=True)
    quantity: Integer(default=1)
    price = ValueObject(Money)

    order = Reference(Order)


class Account(BaseAggregate):
    label: String(max_length=50, required=False)
    profile = HasOne("Profile")


class Profile(BaseEntity):
    handle: String(max_length=50, required=True)

    account = Reference(Account)


class Warehouse(BaseAggregate):
    label: String(max_length=50, required=False)
    zones = HasMany("Zone")


class Zone(BaseEntity):
    name: String(max_length=50, required=True)
    bins = HasMany("Bin")

    warehouse = Reference(Warehouse)


class Bin(BaseEntity):
    code: String(max_length=50, required=True)

    zone = Reference(Zone)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Counter)
    test_domain.register(Money)
    test_domain.register(Order)
    test_domain.register(OrderLine, part_of=Order)
    test_domain.register(Account)
    test_domain.register(Profile, part_of=Account)
    test_domain.register(Warehouse)
    test_domain.register(Zone, part_of=Warehouse)
    test_domain.register(Bin, part_of=Zone)
    test_domain.init(traverse=False)


@pytest.mark.basic_storage
class TestVersionIncrement:
    """Verify _version increments on each save."""

    def test_initial_version_is_minus_one(self, test_domain):
        counter = Counter(name="test", value=0)
        assert counter._version == -1

    def test_version_is_zero_after_first_persist(self, test_domain):
        counter = Counter(name="test", value=0)

        with UnitOfWork():
            test_domain.repository_for(Counter).add(counter)

        retrieved = test_domain.repository_for(Counter).get(counter.id)
        assert retrieved._version == 0

    def test_version_increments_on_update(self, test_domain):
        identifier = str(uuid4())
        counter = Counter(id=identifier, name="test", value=0)

        with UnitOfWork():
            test_domain.repository_for(Counter).add(counter)

        # First update
        retrieved = test_domain.repository_for(Counter).get(identifier)
        retrieved.value = 1
        with UnitOfWork():
            test_domain.repository_for(Counter).add(retrieved)

        after_first = test_domain.repository_for(Counter).get(identifier)
        assert after_first._version == 1

        # Second update
        after_first.value = 2
        with UnitOfWork():
            test_domain.repository_for(Counter).add(after_first)

        after_second = test_domain.repository_for(Counter).get(identifier)
        assert after_second._version == 2


@pytest.mark.basic_storage
class TestConcurrentUpdateDetection:
    """Verify stale writes are rejected with ExpectedVersionError."""

    def test_stale_write_raises_expected_version_error(self, test_domain):
        identifier = str(uuid4())
        counter = Counter(id=identifier, name="race", value=0)

        with UnitOfWork():
            test_domain.repository_for(Counter).add(counter)

        # Load two copies of the same aggregate
        copy1 = test_domain.repository_for(Counter).get(identifier)
        copy2 = test_domain.repository_for(Counter).get(identifier)

        # First copy succeeds
        copy1.value = 10
        with UnitOfWork():
            test_domain.repository_for(Counter).add(copy1)

        # Second copy (stale) should fail
        copy2.value = 20
        with pytest.raises(ExpectedVersionError), UnitOfWork():
            test_domain.repository_for(Counter).add(copy2)

    def test_value_unchanged_after_concurrent_conflict(self, test_domain):
        identifier = str(uuid4())
        counter = Counter(id=identifier, name="conflict", value=0)

        with UnitOfWork():
            test_domain.repository_for(Counter).add(counter)

        copy1 = test_domain.repository_for(Counter).get(identifier)
        copy2 = test_domain.repository_for(Counter).get(identifier)

        # First copy wins
        copy1.value = 42
        with UnitOfWork():
            test_domain.repository_for(Counter).add(copy1)

        # Second copy fails
        copy2.value = 99
        with pytest.raises(ExpectedVersionError), UnitOfWork():
            test_domain.repository_for(Counter).add(copy2)

        # Verify the winning value persisted
        final = test_domain.repository_for(Counter).get(identifier)
        assert final.value == 42


@pytest.mark.basic_storage
class TestVersionRoundTrip:
    """Verify _version survives persist/retrieve cycles."""

    def test_version_matches_after_initial_persist(self, test_domain):
        counter = Counter(name="roundtrip", value=0)

        with UnitOfWork():
            test_domain.repository_for(Counter).add(counter)

        retrieved = test_domain.repository_for(Counter).get(counter.id)
        assert retrieved._version == 0

    def test_version_matches_after_update(self, test_domain):
        identifier = str(uuid4())
        counter = Counter(id=identifier, name="roundtrip", value=0)

        with UnitOfWork():
            test_domain.repository_for(Counter).add(counter)

        # Update and verify version round-trips
        retrieved = test_domain.repository_for(Counter).get(identifier)
        assert retrieved._version == 0

        retrieved.value = 5
        with UnitOfWork():
            test_domain.repository_for(Counter).add(retrieved)

        updated = test_domain.repository_for(Counter).get(identifier)
        assert updated._version == 1
        assert updated.value == 5


@pytest.mark.basic_storage
class TestReadAfterUpdateInSameUnitOfWork:
    """Read-your-writes consistency: a re-read after an update in the same UoW
    sees the new state (the ORM applies the change to the session-tracked
    instance). This is a consistency guard, not the lost-update test — see the
    postgres concurrency test for that."""

    def test_reget_in_same_uow_reflects_the_update(self, test_domain):
        repo = test_domain.repository_for(Counter)
        counter = Counter(name="c", value=0)
        with UnitOfWork():
            repo.add(counter)
        counter_id = counter.id

        with UnitOfWork():
            loaded = repo.get(counter_id)
            loaded.value = 99
            repo.add(loaded)
            refetched = repo.get(counter_id)
            assert refetched.value == 99
            assert refetched._version == 1


@pytest.mark.basic_storage
class TestUpdateOfDeletedAggregate:
    """Saving an aggregate whose row was deleted raises ObjectNotFoundError,
    not ExpectedVersionError."""

    def test_saving_a_deleted_aggregate_raises_object_not_found(self, test_domain):
        repo = test_domain.repository_for(Counter)
        counter = Counter(name="c", value=0)
        with UnitOfWork():
            repo.add(counter)
        counter_id = counter.id

        # Load a stale copy, then delete the row out from under it.
        stale = repo.get(counter_id)
        with UnitOfWork():
            repo._dao.delete(repo.get(counter_id))

        stale.value = 1
        with pytest.raises(ObjectNotFoundError), UnitOfWork():
            repo.add(stale)


@pytest.mark.basic_storage
class TestStandaloneStaleWrite:
    """A stale write outside any UnitOfWork still raises ExpectedVersionError
    (and cleans up its standalone session)."""

    def test_standalone_stale_save_raises_expected_version_error(self, test_domain):
        dao = test_domain.repository_for(Counter)._dao
        counter = Counter(name="c", value=0)
        test_domain.repository_for(Counter).add(counter)
        counter_id = counter.id

        first = test_domain.repository_for(Counter).get(counter_id)
        second = test_domain.repository_for(Counter).get(counter_id)

        # Both loaded version 0; commit the first (standalone), then the second
        # is stale. No UnitOfWork wraps these, so the DAO runs standalone.
        first.value = 1
        dao.save(first)

        second.value = 2
        with pytest.raises(ExpectedVersionError):
            dao.save(second)


@pytest.mark.basic_storage
class TestChildOnlyMutationVersioning:
    """The aggregate root is the concurrency boundary: a change confined to a
    child entity's own field must advance the root's _version, so a stale
    child-only write is rejected instead of silently overwriting."""

    def _seed_order(self, test_domain):
        """Persist an order with a single line at version 0; return its id."""
        with UnitOfWork():
            order = Order(label="seed")
            order.add_lines(
                OrderLine(sku="A", quantity=1, price=Money(currency="USD", amount=5))
            )
            test_domain.repository_for(Order).add(order)
        return order.id

    def test_child_scalar_edit_bumps_root_version(self, test_domain):
        order_id = self._seed_order(test_domain)
        assert test_domain.repository_for(Order).get(order_id)._version == 0

        with UnitOfWork():
            loaded = test_domain.repository_for(Order).get(order_id)
            loaded.lines[0].quantity = 99
            test_domain.repository_for(Order).add(loaded)

        persisted = test_domain.repository_for(Order).get(order_id)
        assert persisted._version == 1
        assert persisted.lines[0].quantity == 99

    def test_child_value_object_edit_bumps_root_version(self, test_domain):
        """A value-object field edit on a child is a child change too — it must
        advance the root version, not just scalar-field edits."""
        order_id = self._seed_order(test_domain)

        with UnitOfWork():
            loaded = test_domain.repository_for(Order).get(order_id)
            loaded.lines[0].price = Money(currency="EUR", amount=20)
            test_domain.repository_for(Order).add(loaded)

        persisted = test_domain.repository_for(Order).get(order_id)
        assert persisted._version == 1
        assert persisted.lines[0].price == Money(currency="EUR", amount=20)

    def test_hasone_child_edit_bumps_root_version(self, test_domain):
        """A change confined to a HasOne child advances the root version too."""
        with UnitOfWork():
            account = Account(label="seed")
            account.profile = Profile(handle="original")
            test_domain.repository_for(Account).add(account)
        account_id = account.id
        assert test_domain.repository_for(Account).get(account_id)._version == 0

        with UnitOfWork():
            loaded = test_domain.repository_for(Account).get(account_id)
            loaded.profile.handle = "updated"
            test_domain.repository_for(Account).add(loaded)

        persisted = test_domain.repository_for(Account).get(account_id)
        assert persisted._version == 1
        assert persisted.profile.handle == "updated"

    def test_nested_grandchild_edit_bumps_root_version(self, test_domain):
        """The root is the boundary for the whole tree: an edit confined to a
        grandchild (a child of a child) advances the root version too."""
        with UnitOfWork():
            warehouse = Warehouse(label="seed")
            zone = Zone(name="A")
            zone.add_bins(Bin(code="A-1"))
            warehouse.add_zones(zone)
            test_domain.repository_for(Warehouse).add(warehouse)
        warehouse_id = warehouse.id
        assert test_domain.repository_for(Warehouse).get(warehouse_id)._version == 0

        with UnitOfWork():
            loaded = test_domain.repository_for(Warehouse).get(warehouse_id)
            loaded.zones[0].bins[0].code = "A-2"
            test_domain.repository_for(Warehouse).add(loaded)

        persisted = test_domain.repository_for(Warehouse).get(warehouse_id)
        assert persisted._version == 1
        assert persisted.zones[0].bins[0].code == "A-2"

    def test_unmodified_reload_does_not_bump_version(self, test_domain):
        """A load-and-re-add with no change must not advance the version — the
        re-save only fires on an actual child mutation."""
        order_id = self._seed_order(test_domain)

        with UnitOfWork():
            unchanged = test_domain.repository_for(Order).get(order_id)
            assert not unchanged.state_.is_changed
            test_domain.repository_for(Order).add(unchanged)

        assert test_domain.repository_for(Order).get(order_id)._version == 0

    def test_adding_a_child_alone_does_not_bump_version(self, test_domain):
        """Adding a HasMany child (no edit to an existing child) is out of scope:
        it persists the new child but does not advance the root version."""
        order_id = self._seed_order(test_domain)

        with UnitOfWork():
            loaded = test_domain.repository_for(Order).get(order_id)
            loaded.add_lines(OrderLine(sku="B", quantity=2))
            test_domain.repository_for(Order).add(loaded)

        persisted = test_domain.repository_for(Order).get(order_id)
        assert persisted._version == 0  # add is out of scope, no bump
        assert len(persisted.lines) == 2  # but the new child was persisted

    def test_removing_a_child_alone_does_not_bump_version(self, test_domain):
        """Removing a HasMany child is out of scope too: it deletes the child row
        but does not advance the root version."""
        with UnitOfWork():
            order = Order(label="seed")
            order.add_lines(OrderLine(sku="A", quantity=1))
            order.add_lines(OrderLine(sku="B", quantity=2))
            test_domain.repository_for(Order).add(order)
        order_id = order.id

        with UnitOfWork():
            loaded = test_domain.repository_for(Order).get(order_id)
            loaded.remove_lines(loaded.lines[0])
            test_domain.repository_for(Order).add(loaded)

        persisted = test_domain.repository_for(Order).get(order_id)
        assert persisted._version == 0  # remove is out of scope, no bump
        assert len(persisted.lines) == 1  # but the child was removed

    def test_stale_child_only_write_raises_expected_version_error(self, test_domain):
        order_id = self._seed_order(test_domain)

        # Two copies both loaded at version 0.
        copy1 = test_domain.repository_for(Order).get(order_id)
        copy2 = test_domain.repository_for(Order).get(order_id)

        # First copy mutates a child field and wins.
        copy1.lines[0].quantity = 10
        with UnitOfWork():
            test_domain.repository_for(Order).add(copy1)

        # Second copy is stale; a child-only mutation must still be rejected.
        copy2.lines[0].quantity = 20
        with pytest.raises(ExpectedVersionError), UnitOfWork():
            test_domain.repository_for(Order).add(copy2)

        # The first writer's value survived.
        final = test_domain.repository_for(Order).get(order_id)
        assert final._version == 1
        assert final.lines[0].quantity == 10

    def test_standalone_stale_child_write_does_not_leak_uow(self, test_domain):
        """A stale child-only write through a standalone ``add`` (no enclosing
        UoW) raises ExpectedVersionError and leaves no dangling in-progress UoW,
        so the next operation runs cleanly rather than inside a poisoned one."""
        order_id = self._seed_order(test_domain)

        copy1 = test_domain.repository_for(Order).get(order_id)
        copy2 = test_domain.repository_for(Order).get(order_id)

        # Standalone add (no UnitOfWork wrapper); first writer wins.
        copy1.lines[0].quantity = 10
        test_domain.repository_for(Order).add(copy1)

        copy2.lines[0].quantity = 20
        with pytest.raises(ExpectedVersionError):
            test_domain.repository_for(Order).add(copy2)

        # The internally-started UoW was rolled back, not left in progress.
        assert not (current_uow and current_uow.in_progress)

        # A subsequent operation still works and sees the winner's value.
        final = test_domain.repository_for(Order).get(order_id)
        assert final._version == 1
        assert final.lines[0].quantity == 10
