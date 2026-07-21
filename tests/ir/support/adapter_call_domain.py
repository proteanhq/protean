"""Fixture module whose method bodies call ``protean.adapters.*``.

Exercises the ADAPTER_CALL_IN_DOMAIN on-path: the rule reads each registered
element's method bodies through the behavioral view and flags a call whose
callee statically resolves under ``protean.adapters``. Nothing here executes —
the rule only parses the source — so the adapter call sites never need the
adapter to be constructable, and the string paths need not exist at runtime.

The unique catch this rule adds over INFRA_IMPORT_IN_DOMAIN is the call reached
through ``import protean`` attribute access: the import rule's module-level
name-prefix check sees only ``protean`` and does not flag it, yet the call site
``protean.adapters...(...)`` is real runtime coupling. So this module imports
only ``protean`` at the top — no top-level ``from protean.adapters`` — to keep
the positive cases the *unique* catch of the call-site rule.
"""

import protean
from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.fields import String


class AdapterCallOrder(BaseAggregate):
    """Positive: a method reaches an adapter through ``import protean``
    attribute access — the coupling INFRA_IMPORT_IN_DOMAIN's module-level
    name-prefix check misses."""

    name = String(max_length=50)

    def provision(self):
        return protean.adapters.broker.inline.InlineBroker("default", None, {})


class AdapterCallMoney(BaseValueObject):
    """Positive, non-aggregate: a value object whose own method calls an
    adapter. Proves the rule is element-type-agnostic — it fires on any
    registered element bucket, not only aggregates."""

    amount = String(max_length=10)

    def provision(self):
        return protean.adapters.broker.inline.InlineBroker("default", None, {})


class SiblingPrefixOrder(BaseAggregate):
    """Negative — sibling prefix: the callee resolves to ``protean.adaptersfoo``,
    which shares the ``protean.adapters`` string prefix but is a *different*
    package. The dot-boundary guard (``startswith("protean.adapters.")``, not a
    bare string-prefix test) must not flag it."""

    name = String(max_length=50)

    def provision(self):
        return protean.adaptersfoo.broker.inline.InlineBroker("default", None, {})


class MultiCallOrder(BaseAggregate):
    """Positive, multi-site: two adapter call-sites in one method → two
    diagnostics, emitted in source order."""

    name = String(max_length=50)

    def provision(self):
        first = protean.adapters.broker.inline.InlineBroker("a", None, {})
        second = protean.adapters.broker.redis.RedisBroker("b", None, {})
        return first, second


class LocalImportOrder(BaseAggregate):
    """Negative — unresolved callee: the adapter is bound by a function-local
    import, so it is not in the module symbol table and does not resolve."""

    name = String(max_length=50)

    def provision(self):
        from protean.adapters.broker.inline import InlineBroker as LocalBroker

        return LocalBroker("default", None, {})


class InjectedReceiverOrder(BaseAggregate):
    """Negative — unresolved callee: the adapter arrives through a fetched
    local-variable receiver, so its root does not resolve and the call is
    skipped rather than guessed at."""

    name = String(max_length=50)

    def provision(self):
        broker = self.brokers["default"]
        return broker.publish("stream", {})


class CleanOrder(BaseAggregate):
    """Clean: a self-rooted repository/DAO call resolves to no FQN, and a
    resolved framework call names a non-adapter symbol — neither touches
    ``protean.adapters``, so the rule must not over-flag either."""

    name = String(max_length=50)

    def total(self):
        # ``protean.utils.fqn`` resolves (via ``import protean``) but is not an
        # adapter, so the resolved-but-not-adapter path is skipped, not flagged.
        protean.utils.fqn(type(self))
        return self._dao.filter(name="x")


class UnregisteredHelper:
    """A plain class with an identical adapter call, deliberately left
    unregistered, to prove the rule is domain-scoped: it is never visited, so
    it is never flagged."""

    def provision(self):
        return protean.adapters.broker.inline.InlineBroker("default", None, {})
