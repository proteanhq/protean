"""Fixture module for UNRAISED_EVENT.

The rule reads each aggregate/entity method body through the behavioral view. An
event counts as raised when one method both calls ``raise_`` and constructs that
event. Nothing here executes: the rule only parses the source, so the raises
never need a running domain.

The two facts behind a raise are separate. ``self.raise_(Opened(...))`` records
a ``raise_`` call and a construction of ``Opened``; the rule ties them at the
method level. ``User.register`` proves the factory idiom: ``user.raise_(...)``
leaves the receiver role ``UNKNOWN``, and the rule still recognizes it because it
keys on the ``raise_`` method name and the constructed event, never on the role.
"""

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.fields import HasMany, Identifier, Reference, String


class Opened(BaseEvent):
    account_id = Identifier()


class Closed(BaseEvent):
    account_id = Identifier()


class Account(BaseAggregate):
    """``open`` raises ``Opened`` through ``self.raise_``. Nothing raises
    ``Closed``, so ``Closed`` is the unraised event."""

    name = String(max_length=50)

    def open(self):
        self.raise_(Opened(account_id=self.id))


class Registered(BaseEvent):
    user_id = Identifier()


class User(BaseAggregate):
    """``register`` raises ``Registered`` through the factory idiom: the raise is
    on a local ``user``, so the receiver role is ``UNKNOWN``."""

    name = String(max_length=50)

    @classmethod
    def register(cls, name):
        user = cls(name=name)
        user.raise_(Registered(user_id=user.id))
        return user


class Dispatched(BaseEvent):
    order_id = Identifier()


class Shipped(BaseEvent):
    order_id = Identifier()


class Order(BaseAggregate):
    """``dispatch`` raises ``Dispatched``. ``Shipped`` is registered
    ``published`` but nothing raises it, so it is still in scope for this rule."""

    name = String(max_length=50)

    def dispatch(self):
        self.raise_(Dispatched(order_id=self.id))


class Noted(BaseEvent):
    note_id = Identifier()


class Note(BaseAggregate):
    """Analyzed (the index reaches its source) but has no methods, so its
    ``Noted`` event is unraised and flagged. The contrast to a fail-open cluster
    whose classes the index cannot reach."""

    text = String(max_length=50)


class LineAdded(BaseEvent):
    basket_id = Identifier()


class BasketLine(BaseEntity):
    """An entity that raises ``LineAdded``. Proves the rule scans entity methods,
    not only the aggregate root."""

    sku = String(max_length=50)
    basket = Reference("Basket")

    def add(self):
        self.raise_(LineAdded(basket_id=self.id))


class Basket(BaseAggregate):
    name = String(max_length=50)
    lines = HasMany(BasketLine)


class BaseCreated(BaseEvent):
    base_id = Identifier()


class AbstractBase(BaseAggregate):
    """Registered ``abstract``. Its ``BaseCreated`` event is skipped: the rule
    excludes clusters whose aggregate is abstract, as the other cluster-walking
    rules do."""

    name = String(max_length=50)


class Ledger(BaseAggregate):
    """Registered ``fact_events``. The generated fact event is auto-generated,
    so it is excluded even though nothing raises it."""

    balance = String(max_length=50)


class Vanished(BaseEvent):
    ghost_id = Identifier()
