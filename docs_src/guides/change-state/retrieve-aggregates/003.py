from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from protean import Domain
from protean.fields import DateTime, Float, String
from protean.utils.query import Q

domain = Domain()


# --8<-- [start:functions]
@domain.aggregate
class Order:
    status: String(max_length=20, default="pending")
    total: Float()
    shipping_region: String(max_length=10)
    placed_at: DateTime()
    due_date: DateTime()


def overdue_orders(grace_days: int = 0) -> Q:
    """Orders past their payment deadline."""
    deadline = datetime.now(UTC) - timedelta(days=grace_days)
    return Q(status="pending", due_date__lt=deadline)


def high_value_orders(min_amount: Decimal = Decimal(1000)) -> Q:
    """Orders exceeding a monetary threshold."""
    return Q(total__gte=min_amount)


def in_region(region: str) -> Q:
    """Orders shipping to a specific region."""
    return Q(shipping_region=region)


def recent_orders(within_days: int = 7) -> Q:
    """Orders placed in the last few days."""
    return Q(placed_at__gte=datetime.now(UTC) - timedelta(days=within_days))


# --8<-- [end:functions]


# The custom repository is registered before `init`, so that
# `repository_for(Order)` returns it.
# --8<-- [start:repository]
@domain.repository(part_of=Order)
class OrderRepository:
    def critical_orders(self) -> list:
        return self.find(overdue_orders(grace_days=3) & high_value_orders(5000)).items

    def has_overdue_in_region(self, region: str) -> bool:
        return self.exists(overdue_orders() & in_region(region))


# --8<-- [end:repository]


# --8<-- [start:specification]
class Specification(ABC):
    """Base class for domain query specifications."""

    @abstractmethod
    def to_query(self) -> Q:
        """Return Q criteria for database queries."""
        ...

    @abstractmethod
    def is_satisfied_by(self, entity) -> bool:
        """Test whether an entity matches this rule in memory."""
        ...

    def __and__(self, other: "Specification") -> "Specification":
        return _And(self, other)

    def __or__(self, other: "Specification") -> "Specification":
        return _Or(self, other)

    def __invert__(self) -> "Specification":
        return _Not(self)


class _And(Specification):
    def __init__(self, left, right):
        self.left, self.right = left, right

    def to_query(self) -> Q:
        return self.left.to_query() & self.right.to_query()

    def is_satisfied_by(self, entity) -> bool:
        return self.left.is_satisfied_by(entity) and self.right.is_satisfied_by(entity)


class _Or(Specification):
    def __init__(self, left, right):
        self.left, self.right = left, right

    def to_query(self) -> Q:
        return self.left.to_query() | self.right.to_query()

    def is_satisfied_by(self, entity) -> bool:
        return self.left.is_satisfied_by(entity) or self.right.is_satisfied_by(entity)


class _Not(Specification):
    def __init__(self, spec):
        self.spec = spec

    def to_query(self) -> Q:
        return ~self.spec.to_query()

    def is_satisfied_by(self, entity) -> bool:
        return not self.spec.is_satisfied_by(entity)


# --8<-- [end:specification]


# --8<-- [start:concrete_specifications]
class OverdueOrders(Specification):
    def __init__(self, grace_days: int = 0):
        self.grace_period = timedelta(days=grace_days)

    def to_query(self) -> Q:
        deadline = datetime.now(UTC) - self.grace_period
        return Q(status="pending", due_date__lt=deadline)

    def is_satisfied_by(self, order) -> bool:
        deadline = datetime.now(UTC) - self.grace_period
        return order.status == "pending" and order.due_date < deadline


class HighValueOrders(Specification):
    def __init__(self, min_amount: Decimal = Decimal(1000)):
        self.min_amount = min_amount

    def to_query(self) -> Q:
        return Q(total__gte=self.min_amount)

    def is_satisfied_by(self, order) -> bool:
        return order.total >= self.min_amount


# --8<-- [end:concrete_specifications]


# Stands in for the application's own notification code.
reminders = []


def send_reminder(order):
    reminders.append(order.id)


domain.init(traverse=False)
context = domain.domain_context()
context.push()

now = datetime.now(UTC)
for order in [
    # Overdue past a three-day grace period, high value, shipping to the US
    Order(
        id="A",
        total=7500,
        shipping_region="US",
        placed_at=now - timedelta(days=20),
        due_date=now - timedelta(days=10),
    ),
    # Overdue by a day, placed recently, shipping to the EU
    Order(
        id="B",
        total=1200,
        shipping_region="EU",
        placed_at=now - timedelta(days=3),
        due_date=now - timedelta(days=1),
    ),
    # Paid, so never overdue, high value, shipping to the US
    Order(
        id="C",
        status="paid",
        total=9000,
        shipping_region="US",
        placed_at=now - timedelta(days=30),
        due_date=now - timedelta(days=10),
    ),
    # Not yet due, low value, placed recently
    Order(
        id="D",
        total=300,
        shipping_region="US",
        placed_at=now - timedelta(days=1),
        due_date=now + timedelta(days=5),
    ),
]:
    domain.repository_for(Order).add(order)

# --8<-- [start:compose]
repo = domain.repository_for(Order)

# Find all overdue orders
overdue = repo.find(overdue_orders())

# Compose: overdue AND high-value
critical = repo.find(overdue_orders(grace_days=3) & high_value_orders(5000))

# Compose: high-value in a specific region
regional = repo.find(high_value_orders() & in_region("US"))

# Negate: orders that are NOT recent
stale = repo.find(~recent_orders(within_days=7))

# Check existence
needs_escalation = repo.exists(overdue_orders() & high_value_orders(5000))
# --8<-- [end:compose]
overdue_and_high_value = critical

# --8<-- [start:queryset]
results = (
    repo.query.filter(overdue_orders() & in_region("US"))
    .order_by("-total")
    .limit(20)
    .all()
)
# --8<-- [end:queryset]
overdue_in_us = results

# --8<-- [start:use_specifications]
# Database query
critical = OverdueOrders(grace_days=3) & HighValueOrders(min_amount=5000)
results = repo.find(critical.to_query())


# In-memory check (no database hit)
def remind_if_overdue(order):
    if OverdueOrders().is_satisfied_by(order):
        send_reminder(order)


# --8<-- [end:use_specifications]

context.pop()
