from typing import Any, ClassVar, Self, TypeVar

from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, _derive_element_class
from protean.utils.container import DerivedDefault, Element, OptionsMixin
from protean.utils.mixins import HandlerMixin, handle


class BaseProjector(Element, HandlerMixin, OptionsMixin):
    """Base class for projectors, which keep a projection up to date from
    domain events.

    A projector names its projection with ``projector_for`` and can listen to
    events from several aggregates. The ``@handle`` decorator, or its alias
    ``@on``, maps an event type to a handler method. A handler method receives
    the event as its only argument and creates, updates or deletes the
    projection record. See the Projectors guide for a walk-through.

    **Meta Options**

    | Option | Type | Description |
    |--------|------|-------------|
    | ``projector_for`` | ``type`` | The projection class this projector maintains. Required. |
    | ``aggregates`` | ``list`` | Aggregate classes whose events this projector listens to. |
    | ``stream_categories`` | ``list`` | Explicit stream categories to subscribe to. Overrides ``aggregates``. |
    | ``retries`` | ``int`` | Max retry attempts on transient exceptions. Overrides ``server.transient_retry``; ``None`` defers to it. |
    | ``backoff`` | ``str`` | Retry delay strategy: ``"exponential"``, ``"linear"``, or ``"fixed"``. |
    | ``retry_exceptions`` | ``list`` | Exception types (classes or dotted paths) treated as transient for retry. |
    | ``sequential_by`` | ``str`` | Partition key field name for per-key sequential processing (ADR-0028). |
    | ``subscription_type`` | ``str`` | ``"stream"`` or ``"event_store"``. ``None`` uses the domain default. |
    | ``subscription_profile`` | ``str`` | Named subscription profile, such as ``"projection"``. |
    | ``subscription_config`` | ``dict`` | Custom subscription settings that override the profile. |
    | ``idempotent`` | ``bool`` | Record a delivery marker per event so a redelivered event is applied once. |
    | ``suppress_checks`` | ``tuple`` | Diagnostic codes ``protean check`` should not report for this projector. |

    Example::

        @domain.projector(projector_for=OrderSummary, aggregates=[Order])
        class OrderSummaryProjector(BaseProjector):

            @on(OrderPlaced)
            def on_order_placed(self, event):
                repo = current_domain.repository_for(OrderSummary)
                repo.add(OrderSummary(
                    order_id=event.order_id,
                    status="placed",
                ))

            @on(OrderShipped)
            def on_order_shipped(self, event):
                repo = current_domain.repository_for(OrderSummary)
                summary = repo.get(event.order_id)
                summary.status = "shipped"
                repo.add(summary)
    """

    element_type = DomainObjects.PROJECTOR

    _default_options: ClassVar[list[tuple[str, Any]]] = [
        # ``projector_for`` resolves to ``None`` whenever this default is
        # consulted (a concrete value is already on ``meta_`` and skips it).
        ("projector_for", None),
        # Use aggregates if specified, otherwise default to empty list.
        ("aggregates", []),
        # Use stream categories if specified. Otherwise, if aggregates are
        # specified, gather stream categories from each aggregate; if neither
        # is specified, default to an empty list. This default is only
        # consulted when ``stream_categories`` is unset.
        (
            "stream_categories",
            DerivedDefault(
                lambda cls: [
                    aggregate.meta_.stream_category
                    for aggregate in getattr(cls.meta_, "aggregates", [])
                ]
            ),
        ),
        # Transient-failure retry policy (parity with event handlers and
        # command handlers). ``retries`` (int) sets the max retry attempts
        # on transient exceptions and overrides the domain-level
        # ``server.transient_retry`` config; ``None`` defers to it.
        # ``backoff`` selects the delay strategy ("exponential" | "linear"
        # | "fixed"). ``retry_exceptions`` overrides which exception types
        # are treated as transient (classes or dotted paths). The shared
        # handler wrapper (``protean.utils.mixins``) already consumes these.
        ("retries", None),
        ("backoff", None),
        ("retry_exceptions", None),
        # Partition-per-key sequential processing (ADR-0028), with the same
        # meaning as on event handlers: the name of a direct attribute on
        # every event this projector handles. Each handled event's stream
        # category is partitioned by that key. ``None`` disables partitioning.
        ("sequential_by", None),
        # Subscription configuration options (parity with event handlers and PMs)
        ("subscription_type", None),
        ("subscription_profile", None),
        ("subscription_config", {}),
        # Consume-side idempotency: when True, each handler method records a
        # (message_id, handler) marker in the same UnitOfWork as its
        # read-model write, so a redelivered event is applied exactly once
        # on a transactional provider. See ADR-0017.
        ("idempotent", False),
        ("suppress_checks", ()),
    ]

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        if cls is BaseProjector:
            raise NotSupportedError("BaseProjector cannot be instantiated")
        return super().__new__(cls)


_T = TypeVar("_T", bound=OptionsMixin)


def projector_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
    element_cls = _derive_element_class(element_cls, BaseProjector, **opts)

    if not element_cls.meta_.projector_for:
        raise IncorrectUsageError(
            f"Projector `{element_cls.__name__}` needs to be associated with a Projection"
        )

    # Throw error if neither aggregates nor stream categories are specified
    if not (element_cls.meta_.aggregates or element_cls.meta_.stream_categories):
        raise IncorrectUsageError(
            f"Projector `{element_cls.__name__}` needs to be associated with at least one Aggregate or Stream Category"
        )

    return element_cls


# `on` is a shortcut for `handle` in the context of projectors
on = handle
