from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import Element, OptionsMixin
from protean.utils.mixins import HandlerMixin, handle
from typing import Any, TypeVar


class BaseProjector(Element, HandlerMixin, OptionsMixin):
    """Base class for projectors that maintain read-optimized projections by
    listening to domain events.

    Projectors are always associated with a projection via ``projector_for``
    and use the ``@handle`` (or its alias ``@on``) decorator to map specific
    event types to handler methods. Unlike generic event handlers, projectors
    explicitly target a projection and can listen to events from multiple
    aggregates.

    Handler methods receive the event as their only argument and are
    responsible for creating, updating, or deleting the projection record.

    **Meta Options**

    | Option | Type | Description |
    |--------|------|-------------|
    | ``projector_for`` | ``type`` | The projection class this projector maintains. Required. |
    | ``aggregates`` | ``list`` | Aggregate classes whose events this projector listens to. |
    | ``stream_categories`` | ``list`` | Explicit stream categories to subscribe to. Overrides ``aggregates``. |

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

    @classmethod
    def _default_options(cls):
        projector_for = (
            getattr(cls.meta_, "projector_for")
            if hasattr(cls.meta_, "projector_for")
            else None
        )

        # Use aggregates if specified, otherwise default to empty list
        aggregates = (
            getattr(cls.meta_, "aggregates") if hasattr(cls.meta_, "aggregates") else []
        )

        # Use stream categories if specified. Otherwise,
        #   If aggregates are specified, gather stream categories from each aggregate
        #   If no stream categories nor aggregates are specified, default to empty list
        #   If both are specified, use stream categories
        stream_categories = (
            getattr(cls.meta_, "stream_categories")
            if hasattr(cls.meta_, "stream_categories")
            else []
        )

        # If aggregates are specified and stream categories are not, gather stream categories from each aggregate
        if aggregates and not stream_categories:
            stream_categories = [
                aggregate.meta_.stream_category for aggregate in aggregates
            ]

        return [
            ("projector_for", projector_for),
            ("aggregates", aggregates),
            ("stream_categories", stream_categories),
        ]

    def __new__(cls, *args, **kwargs):
        if cls is BaseProjector:
            raise NotSupportedError("BaseProjector cannot be instantiated")
        return super().__new__(cls)


_T = TypeVar("_T")


def projector_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
    element_cls = derive_element_class(element_cls, BaseProjector, **opts)

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
