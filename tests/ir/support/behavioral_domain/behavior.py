"""Method bodies that exercise the behavioral fact catalog.

The elements here are registered as a real domain by the consuming test, so a
construction (``Order(...)``, ``OrderShipped(...)``) resolves to a *registered*
element FQN — which is what turns a call into a construction fact. Their
``__module__`` and ``__qualname__`` keep pointing at this file, the name both
resolution doors key on.

Each method carries a deliberate shape a test asserts:

- ``Order.ship`` — a read (``self.total``), a write (``self.status = ...``), a
  ``self.raise_(...)`` call, and an ``OrderShipped(...)`` construction nested in
  it.
- ``Order.restock`` — an augmented write (``self.stock += 1``), which the
  grammar models as a store and the catalog records as a write.
- ``OrderRepository.active`` — a recognized repository query on ``self._dao``,
  naming the ``status`` field.
- ``OrderRepository.between`` — two repository queries in one body: the first
  names two fields (``status``, ``channel``), the second one (``reference``), so
  field-name order and call-site order within a method are both observable.
- ``OrderRepository.stale`` — a ``.filter(...)`` on a plain parameter, not
  ``self._dao``: its receiver stays ``UNKNOWN``, so it is a ``filter`` call that
  is *not* a repository filter site.
- ``OrderRepository.by_reference`` — a query whose field comes from an inline
  ``Q(reference=...)``.
- ``OrderRepository.dynamic`` — a ``**filters`` query that names no field.
- ``OrderRepository.seed`` — an ``Order(...)`` construction.
- ``OrderRepository.seed_dynamic`` — an ``Order(**data)`` construction, dynamic.
- ``OrderRepository.in_transaction`` — a call on a ``UnitOfWork()`` receiver.
"""

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.repository import BaseRepository
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Identifier, String
from protean.utils.query import Q


class OrderShipped(BaseEvent):
    order_id = Identifier(identifier=True)


class Order(BaseAggregate):
    order_id = Identifier(identifier=True)
    status = String(max_length=20)
    total = String(max_length=20)
    stock = String(max_length=20)

    def ship(self) -> None:
        """A read, a write, a ``raise_`` call, and a nested construction."""
        current = self.total
        self.status = "shipped"
        self.raise_(OrderShipped(order_id=self.order_id))
        del current

    def restock(self) -> None:
        """An augmented assignment, recorded as a write per its store ctx."""
        self.stock += 1


class OrderRepository(BaseRepository):
    def active(self) -> None:
        """A recognized repository query naming the ``status`` field."""
        self._dao.filter(status="active")

    def between(self) -> None:
        """Two repository queries in one body: the first names two fields, so
        field-name order is pinned; the second names one, so call-site order
        within a method is observable too."""
        self._dao.filter(status="open", channel="web")
        self._dao.filter(reference="latest")

    def stale(self, rows: list) -> None:
        """A ``.filter(...)`` on a plain parameter, not the repository DAO: its
        receiver stays ``UNKNOWN``, so it is a ``filter`` call that is not a
        repository filter site."""
        rows.filter(status="stale")

    def by_reference(self, reference: str) -> None:
        """A query whose field comes from an inline ``Q(reference=...)``."""
        self._dao.find(Q(reference=reference))

    def dynamic(self, **filters: str) -> None:
        """A dynamic-keyword query that names no field."""
        self._dao.filter(**filters)

    def seed(self) -> None:
        """A construction of the registered ``Order`` aggregate."""
        Order(order_id="1", status="new")

    def seed_dynamic(self, data: dict) -> None:
        """A construction spread from a ``**data`` star: dynamic, no field."""
        Order(**data)

    def in_transaction(self) -> None:
        """A call on a ``UnitOfWork()`` receiver."""
        UnitOfWork().commit()
