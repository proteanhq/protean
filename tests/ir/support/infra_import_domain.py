"""Fixture module whose source imports from ``protean.adapters``.

Exercises the INFRA_IMPORT_IN_DOMAIN on-path: the rule resolves each element's
``module`` to this file, AST-parses it, and matches the ``protean.adapters``
import below. The import is intentionally unused — it *is* the coupling the rule
flags — so ``InlineBroker`` is imported only to place a real
``from protean.adapters...`` statement in the module source.

The classes are plain ``BaseAggregate``/``BaseValueObject`` subclasses so the
consuming test can register them onto a domain while preserving their
``__module__`` (which is what ``find_spec`` resolves). ``InfraOrder`` embeds
``Money`` via a ``ValueObject`` field so the value object is placed in the same
cluster, giving the per-element emission test an aggregate *and* a value object
that both live in this infra-importing module.
"""

from protean.adapters.broker.inline import InlineBroker  # noqa: F401
from protean.core.aggregate import BaseAggregate
from protean.core.repository import BaseRepository
from protean.core.value_object import BaseValueObject
from protean.fields import String, ValueObject


class Money(BaseValueObject):
    amount = String(max_length=20)


class InfraOrder(BaseAggregate):
    name = String(max_length=50)
    money = ValueObject(Money)


class InfraOrderRepository(BaseRepository):
    """A repository is *not* a cluster member, so it exercises the scan over
    all registered domain elements — not just aggregate-cluster members."""
