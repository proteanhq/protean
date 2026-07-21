"""Method bodies that exercise the UNINDEXED_FILTER_PATH filter-path join.

Each element is registered as a real domain by the consuming test, so a name
resolves to a *registered* element FQN and a repository query is recognized,
exactly as the fact-catalog corpus does. Indexes are attached at registration
(``domain.register(Order, indexes=[...])``) so one aggregate can serve several
index shapes, keeping the source here about the *call sites* the rule reads.

The shapes each method carries, and the join case they drive:

- ``OrderRepository.filter_indexed`` — ``self._dao.filter(status=...)``, a
  self-rooted repository query (join **case 3**) on an indexed field: covered.
- ``OrderRepository.filter_plain`` — the same shape on a non-indexed field:
  flagged.
- ``OrderRepository.filter_leading_composite`` / ``filter_nonleading_composite``
  — a filter on the leading vs. a non-leading column of a composite index; the
  leading column is covered, the non-leading one is not.
- ``OrderRepository.get_identity`` / ``get_plain`` — ``.get(...)`` on the
  identifier (covered) vs. a plain field (flagged), proving the rule reads the
  whole query surface, not only ``filter``.
- ``OrderRepository.filter_operator_lookup`` /
  ``filter_indexed_operator_lookup`` — an operator lookup (``name__contains`` /
  ``status__in``); the rule strips the ``__<lookup>`` suffix and evaluates the
  base field, so the plain base is flagged and the indexed base is not.
- ``OrderRepository.filter_dynamic`` — ``self._dao.filter(**kwargs)`` names no
  field, so it self-skips (no false positive).
- ``OrderRepository.filter_variable`` — ``rows.filter(name=...)`` on a plain
  parameter, filtering a *non-covered* field: receiver role ``UNKNOWN`` (join
  **case 4**), skipped, and the non-covered field means dropping the
  receiver-role guard would surface a false positive the negative test catches.
- ``OrderRepository.filter_twice`` — two ``filter`` call-sites on the same plain
  field, so per-call-site emission is observable.
- ``AccountRepository.filter_unique`` / ``filter_plain`` — a filter on a
  ``unique`` field (covered by the unique constraint) vs. a plain field.
- ``CustomerRepository.filter_value_object`` / ``filter_scalar`` — a filter
  naming a value-object field (outside the scalar scope, left alone) vs. a plain
  scalar field on the same aggregate (the positive control).
- ``OrderService.by_plain_field`` — a filter path in an application service that
  references the aggregate class by name (``Order.filter(...)``), so its receiver
  resolves to the registered aggregate FQN (join **case 2**, whole-package
  scope).
- ``OrderService.by_variable`` — the same service filtering a plain parameter:
  receiver ``UNKNOWN``, skipped, so the app-service path has its own negative.
"""

from typing import Any

from protean.core.aggregate import BaseAggregate
from protean.core.application_service import BaseApplicationService
from protean.core.event import BaseEvent
from protean.core.repository import BaseRepository
from protean.core.value_object import BaseValueObject
from protean.fields import Identifier, String, ValueObject


class Order(BaseAggregate):
    order_id = Identifier(identifier=True)
    status = String(max_length=20)
    channel = String(max_length=20)
    region = String(max_length=20)
    name = String(max_length=50)


class Account(BaseAggregate):
    account_id = Identifier(identifier=True)
    email = String(max_length=100, unique=True)
    city = String(max_length=50)


class OrderRepository(BaseRepository):
    def filter_indexed(self) -> None:
        """A repository filter on an indexed field (self-rooted, case 3)."""
        self._dao.filter(status="open")

    def filter_plain(self) -> None:
        """A repository filter on a non-indexed field (self-rooted, case 3)."""
        self._dao.filter(name="widget")

    def filter_leading_composite(self) -> None:
        """A filter on the leading column of a composite index — covered."""
        self._dao.filter(channel="web")

    def filter_nonleading_composite(self) -> None:
        """A filter on a non-leading composite column alone — not covered."""
        self._dao.filter(region="emea")

    def get_identity(self) -> None:
        """A ``get`` on the identifier field — implicitly indexed."""
        self._dao.get(order_id="1")

    def get_plain(self) -> None:
        """A ``get`` on a non-identity field — a query surface beyond filter."""
        self._dao.get(name="widget")

    def filter_operator_lookup(self) -> None:
        """An operator lookup (``name__contains``) filters the base field
        ``name``; the rule strips the ``__<lookup>`` suffix and flags the
        uncovered base."""
        self._dao.filter(name__contains="widget")

    def filter_indexed_operator_lookup(self) -> None:
        """An operator lookup on an indexed base field (``status__in``) strips
        to the covered ``status``, so it is not flagged."""
        self._dao.filter(status__in=["open", "closed"])

    def filter_dynamic(self, **filters: str) -> None:
        """A ``**kwargs`` filter that names no field, so it self-skips."""
        self._dao.filter(**filters)

    def filter_variable(self, rows: Any) -> None:
        """A ``.filter`` on a plain parameter, on a *non-covered* field so that
        dropping the receiver-role guard would surface a false positive: receiver
        UNKNOWN, so it is skipped."""
        rows.filter(name="widget")

    def filter_twice(self) -> None:
        """Two call-sites on one plain field, so per-call-site emission shows."""
        self._dao.filter(name="a")
        self._dao.filter(name="b")


class AccountRepository(BaseRepository):
    def filter_unique(self) -> None:
        """A filter on a ``unique`` field — a unique constraint indexes it."""
        self._dao.filter(email="a@b.com")

    def filter_plain(self) -> None:
        """A filter on a non-indexed field — flagged."""
        self._dao.filter(city="paris")


class OrderService(BaseApplicationService):
    def by_plain_field(self) -> None:
        """A filter path in an application service, referencing the aggregate
        by name so its receiver resolves to the registered aggregate FQN
        (case 2, whole-package scope)."""
        Order.filter(name="widget")

    def by_variable(self, rows: Any) -> None:
        """The service filtering a plain parameter: receiver UNKNOWN, skipped."""
        rows.filter(name="widget")


class OrderPlaced(BaseEvent):
    """A registered element that is neither a repository nor an aggregate, used
    to drive the case-4 (receiver resolves to some other element) skip."""

    order_id = Identifier(identifier=True)


class ReceiverCaseService(BaseApplicationService):
    def via_repository_class(self) -> None:
        """A filter whose receiver resolves to a registered **repository** class
        (join case 1): the target is that repository's aggregate."""
        OrderRepository.filter(name="widget")

    def via_event_class(self) -> None:
        """A filter whose receiver resolves to a registered element that is
        neither a repository nor an aggregate (join case 4): skipped."""
        OrderPlaced.filter(name="widget")


class Address(BaseValueObject):
    street = String(max_length=100)
    city = String(max_length=50)


class Customer(BaseAggregate):
    customer_id = Identifier(identifier=True)
    name = String(max_length=50)
    address = ValueObject(Address)


class CustomerRepository(BaseRepository):
    def filter_value_object(self) -> None:
        """A filter naming a value-object field: a value object expands into
        several columns, none named for the field itself, so no ``Index`` on the
        field name could serve it. It is outside the rule's scalar scope and
        left alone — the guard the high-severity red-team finding restored."""
        self._dao.filter(address="x")

    def filter_scalar(self) -> None:
        """A plain scalar filter on the same aggregate — the positive control
        proving the rule is active on this domain, so the value-object skip is
        a real exclusion and not an empty result."""
        self._dao.filter(name="widget")
