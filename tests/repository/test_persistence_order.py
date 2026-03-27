"""Tests that verify parent-before-child persistence ordering.

The repository must persist the aggregate root before its children, and
children before grandchildren.  This top-down ordering is required by
databases that enforce FK constraints immediately (MSSQL, MySQL/InnoDB,
SQLite with ``PRAGMA foreign_keys``).

These tests use a DAO-call recording spy that intercepts *both* the
aggregate root's ``_dao.save()`` and each child's ``_persist_child()``
to assert the complete top-down ordering of all INSERT operations.
"""

from datetime import datetime
from functools import wraps

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.fields import DateTime, Float, HasMany, HasOne, Integer, Reference, String


# ---------------------------------------------------------------------------
# Domain elements: flat (aggregate + direct children)
# ---------------------------------------------------------------------------
class Order(BaseAggregate):
    placed_on: DateTime(default=datetime.now)
    line_items = HasMany("tests.repository.test_persistence_order.OrderItem")
    summary = HasOne("tests.repository.test_persistence_order.OrderSummary")


class OrderItem(BaseEntity):
    product: String(max_length=100)
    qty: Integer(default=1)
    order = Reference(Order)


class OrderSummary(BaseEntity):
    total: Float(default=0.0)
    order = Reference(Order)


# ---------------------------------------------------------------------------
# Domain elements: nested (aggregate → child → grandchild)
# ---------------------------------------------------------------------------
class Company(BaseAggregate):
    name: String(max_length=100)
    departments = HasMany("tests.repository.test_persistence_order.Department")


class Department(BaseEntity):
    name: String(max_length=100)
    employees = HasMany("tests.repository.test_persistence_order.Employee")
    company = Reference(Company)


class Employee(BaseEntity):
    name: String(max_length=100)
    department = Reference(Department)


# ---------------------------------------------------------------------------
# Domain elements: nested HasOne → HasMany (aggregate → HasOne → HasMany)
# ---------------------------------------------------------------------------
class Shipment(BaseAggregate):
    tracking_id: String(max_length=50)
    manifest = HasOne("tests.repository.test_persistence_order.Manifest")


class Manifest(BaseEntity):
    description: String(max_length=200, default="")
    parcels = HasMany("tests.repository.test_persistence_order.Parcel")
    shipment = Reference(Shipment)


class Parcel(BaseEntity):
    weight: Float(default=1.0)
    manifest = Reference(Manifest)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderItem, part_of=Order)
    test_domain.register(OrderSummary, part_of=Order)

    test_domain.register(Company)
    test_domain.register(Department, part_of=Company)
    test_domain.register(Employee, part_of=Department)

    test_domain.register(Shipment)
    test_domain.register(Manifest, part_of=Shipment)
    test_domain.register(Parcel, part_of=Manifest)

    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Helper: record DAO save/delete calls in order
# ---------------------------------------------------------------------------
class DAOCallRecorder:
    """Records the ordering of *all* DAO save calls — both the aggregate
    root's ``_dao.save()`` and each child's ``_persist_child()`` — so that
    tests can assert the complete top-down sequence."""

    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []  # (operation, cls_name, item_id)

    def wrap_dao_save(self, repo):
        """Wrap the repository's ``_dao.save`` to record aggregate root saves."""
        original_save = repo._dao.save

        @wraps(original_save)
        def wrapper(item):
            self.calls.append(("save", item.__class__.__name__, str(item.id)))
            return original_save(item)

        repo._dao.save = wrapper

    def wrap_persist_child(self, repo):
        """Wrap ``_persist_child`` to record child entity saves."""
        original_persist = repo._persist_child

        @wraps(original_persist)
        def wrapper(child_cls, item):
            self.calls.append(("save", child_cls.__name__, str(item.id)))
            return original_persist(child_cls, item)

        repo._persist_child = wrapper

    def wrap_remove_child(self, repo):
        """Wrap ``_remove_child`` to record child entity deletes."""
        original_remove = repo._remove_child

        @wraps(original_remove)
        def wrapper(child_cls, item):
            self.calls.append(("delete", child_cls.__name__, str(item.id)))
            return original_remove(child_cls, item)

        repo._remove_child = wrapper

    def install(self, repo):
        """Install all wrappers on *repo* and return self for convenience."""
        self.wrap_dao_save(repo)
        self.wrap_persist_child(repo)
        self.wrap_remove_child(repo)
        return self


# ---------------------------------------------------------------------------
# Tests: flat aggregate + children (single level)
# ---------------------------------------------------------------------------
class TestFlatPersistenceOrder:
    """Verify aggregate root is saved before HasMany/HasOne children."""

    def test_new_aggregate_with_has_many_children(self, test_domain):
        """A brand-new aggregate with HasMany children should persist
        the aggregate first, then the children."""
        item1 = OrderItem(product="Widget", qty=2)
        item2 = OrderItem(product="Gadget", qty=1)
        order = Order(line_items=[item1, item2])

        repo = test_domain.repository_for(Order)
        recorder = DAOCallRecorder().install(repo)
        repo.add(order)

        # Aggregate root + 2 children = 3 saves
        assert len(recorder.calls) == 3
        # Aggregate root must be the FIRST save
        assert recorder.calls[0] == ("save", "Order", str(order.id))
        # Remaining saves are children
        child_names = {name for _, name, _ in recorder.calls[1:]}
        assert child_names == {"OrderItem"}

        # Verify round-trip
        retrieved = repo.get(order.id)
        assert len(retrieved.line_items) == 2

    def test_new_aggregate_with_has_one_child(self, test_domain):
        """A brand-new aggregate with a HasOne child should persist
        the aggregate first, then the child."""
        summary = OrderSummary(total=42.0)
        order = Order(summary=summary)

        repo = test_domain.repository_for(Order)
        recorder = DAOCallRecorder().install(repo)
        repo.add(order)

        # Aggregate root + 1 child = 2 saves
        assert len(recorder.calls) == 2
        assert recorder.calls[0] == ("save", "Order", str(order.id))
        assert recorder.calls[1] == ("save", "OrderSummary", str(summary.id))

        retrieved = repo.get(order.id)
        assert retrieved.summary is not None
        assert retrieved.summary.total == 42.0

    def test_new_aggregate_with_both_has_many_and_has_one(self, test_domain):
        """New aggregate with both association types persisted in one call.
        Aggregate root must come first in the save sequence."""
        items = [OrderItem(product="A", qty=1), OrderItem(product="B", qty=2)]
        summary = OrderSummary(total=100.0)
        order = Order(line_items=items, summary=summary)

        repo = test_domain.repository_for(Order)
        recorder = DAOCallRecorder().install(repo)
        repo.add(order)

        # Aggregate root + 2 HasMany + 1 HasOne = 4 saves
        assert len(recorder.calls) == 4
        assert recorder.calls[0] == ("save", "Order", str(order.id))
        child_names = {name for _, name, _ in recorder.calls[1:]}
        assert child_names == {"OrderItem", "OrderSummary"}

        retrieved = repo.get(order.id)
        assert len(retrieved.line_items) == 2
        assert retrieved.summary.total == 100.0


# ---------------------------------------------------------------------------
# Tests: nested (aggregate → child → grandchild)
# ---------------------------------------------------------------------------
class TestNestedPersistenceOrder:
    """Verify top-down ordering: aggregate → child → grandchild."""

    def test_new_aggregate_with_nested_children(self, test_domain):
        """Three-level hierarchy persisted in a single add() call.

        Company → Department (HasMany) → Employee (HasMany)

        The persistence order must be:
        1. Company (aggregate root)
        2. Department (child, FK → Company)
        3. Employee (grandchild, FK → Department)
        """
        emp1 = Employee(name="Alice")
        emp2 = Employee(name="Bob")
        dept = Department(name="Engineering", employees=[emp1, emp2])
        company = Company(name="Acme Corp", departments=[dept])

        repo = test_domain.repository_for(Company)
        recorder = DAOCallRecorder().install(repo)
        repo.add(company)

        # Aggregate root + 1 Department + 2 Employees = 4 saves
        assert len(recorder.calls) == 4

        # Company must come first, then Department, then Employees
        assert recorder.calls[0] == ("save", "Company", str(company.id))

        dept_idx = next(
            i for i, (_, name, _) in enumerate(recorder.calls) if name == "Department"
        )
        emp_indices = [
            i for i, (_, name, _) in enumerate(recorder.calls) if name == "Employee"
        ]
        assert dept_idx < min(emp_indices), (
            "Department must be persisted before any Employee"
        )

        # Verify round-trip
        retrieved = repo.get(company.id)
        assert len(retrieved.departments) == 1
        assert len(retrieved.departments[0].employees) == 2

    def test_new_aggregate_with_multiple_nested_branches(self, test_domain):
        """Multiple children each with their own grandchildren."""
        dept1 = Department(
            name="Engineering",
            employees=[Employee(name="Alice"), Employee(name="Bob")],
        )
        dept2 = Department(
            name="Marketing",
            employees=[Employee(name="Charlie")],
        )
        company = Company(name="Acme Corp", departments=[dept1, dept2])

        repo = test_domain.repository_for(Company)
        recorder = DAOCallRecorder().install(repo)
        repo.add(company)

        # Aggregate root + 2 Departments + 3 Employees = 6 saves
        assert len(recorder.calls) == 6

        # Company root must be first
        assert recorder.calls[0] == ("save", "Company", str(company.id))

        # All Department saves come before all Employee saves
        dept_indices = [
            i for i, (_, name, _) in enumerate(recorder.calls) if name == "Department"
        ]
        emp_indices = [
            i for i, (_, name, _) in enumerate(recorder.calls) if name == "Employee"
        ]
        assert max(dept_indices) < min(emp_indices), (
            "All Department saves must complete before any Employee save"
        )

        # Verify round-trip
        retrieved = repo.get(company.id)
        assert len(retrieved.departments) == 2
        total_employees = sum(len(d.employees) for d in retrieved.departments)
        assert total_employees == 3

    def test_has_one_then_has_many_nesting(self, test_domain):
        """Shipment → Manifest (HasOne) → Parcel (HasMany).

        Verifies top-down ordering through HasOne → HasMany nesting.
        """
        parcels = [Parcel(weight=2.5), Parcel(weight=3.0)]
        manifest = Manifest(description="Fragile goods", parcels=parcels)
        shipment = Shipment(tracking_id="TRACK-001", manifest=manifest)

        repo = test_domain.repository_for(Shipment)
        recorder = DAOCallRecorder().install(repo)
        repo.add(shipment)

        # Aggregate root + 1 Manifest + 2 Parcels = 4 saves
        assert len(recorder.calls) == 4

        # Shipment must come first
        assert recorder.calls[0] == ("save", "Shipment", str(shipment.id))

        # Manifest must be saved before Parcels
        manifest_idx = next(
            i for i, (_, name, _) in enumerate(recorder.calls) if name == "Manifest"
        )
        parcel_indices = [
            i for i, (_, name, _) in enumerate(recorder.calls) if name == "Parcel"
        ]
        for parcel_idx in parcel_indices:
            assert manifest_idx < parcel_idx, (
                f"Manifest (index {manifest_idx}) must be persisted before "
                f"Parcel (index {parcel_idx})"
            )

        # Verify round-trip
        retrieved = repo.get(shipment.id)
        assert retrieved.manifest is not None
        assert retrieved.manifest.description == "Fragile goods"
        assert len(retrieved.manifest.parcels) == 2


# ---------------------------------------------------------------------------
# Tests: adding children to existing aggregates
# ---------------------------------------------------------------------------
class TestAddChildrenToExistingAggregate:
    """When the aggregate already exists, child inserts should still work."""

    def test_add_nested_children_to_existing_aggregate(self, test_domain):
        """Add a department with employees to an existing company."""
        company = Company(name="Startup Inc")
        test_domain.repository_for(Company).add(company)

        retrieved = test_domain.repository_for(Company).get(company.id)
        dept = Department(
            name="R&D", employees=[Employee(name="Dave"), Employee(name="Eve")]
        )
        retrieved.add_departments(dept)
        test_domain.repository_for(Company).add(retrieved)

        final = test_domain.repository_for(Company).get(company.id)
        assert len(final.departments) == 1
        assert len(final.departments[0].employees) == 2

    def test_add_grandchildren_to_existing_child(self, test_domain):
        """Add employees to an existing department."""
        dept = Department(name="Sales")
        company = Company(name="BigCo", departments=[dept])
        test_domain.repository_for(Company).add(company)

        retrieved = test_domain.repository_for(Company).get(company.id)
        retrieved.departments[0].add_employees(Employee(name="Frank"))
        retrieved.departments[0].add_employees(Employee(name="Grace"))
        test_domain.repository_for(Company).add(retrieved)

        final = test_domain.repository_for(Company).get(company.id)
        assert len(final.departments[0].employees) == 2
