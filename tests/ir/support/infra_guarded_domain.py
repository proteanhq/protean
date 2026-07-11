"""Fixture module whose only ``protean.adapters`` references are guarded.

The adapter import lives under a ``TYPE_CHECKING`` guard (compile-time only)
and inside a method body (lazy, runtime-optional). Neither introduces the
module-level runtime coupling the rule targets — they are the idiomatic ways to
*avoid* it — so ``INFRA_IMPORT_IN_DOMAIN`` must not flag this module.
"""

from typing import TYPE_CHECKING

from protean.core.aggregate import BaseAggregate
from protean.fields import String

if TYPE_CHECKING:
    from protean.adapters.broker.inline import InlineBroker  # noqa: F401


class GuardedOrder(BaseAggregate):
    name = String(max_length=50)

    def _lazy_broker(self) -> type:
        from protean.adapters.broker.inline import InlineBroker

        return InlineBroker
