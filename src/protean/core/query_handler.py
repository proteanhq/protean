"""Query Handler module for processing domain queries.

This module provides the base class for query handlers, which are responsible
for processing domain queries and returning read-side results. Query handlers
are the read-side counterpart of command handlers.

Unlike command handlers, query handlers:
- Do **not** wrap execution in a UnitOfWork (reads are stateless)
- Always return values
- Are associated with **Projections** (not Aggregates)
- Have no stream/subscription infrastructure (synchronous only)

Example:
    Basic query handler associated with a projection::

        @domain.query_handler(part_of=OrderSummary)
        class OrderSummaryQueryHandler(BaseQueryHandler):
            @read(GetOrdersByCustomer)
            def get_by_customer(self, query: GetOrdersByCustomer):
                view = current_domain.view_for(OrderSummary)
                return view.query.filter(
                    customer_id=query.customer_id
                ).all()

    Usage via domain.dispatch()::

        result = domain.dispatch(
            GetOrdersByCustomer(customer_id="123", status="shipped")
        )
"""

from typing import Any, Optional, TypeVar, Union

from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import Element, OptionsMixin
from protean.utils.mixins import HandlerMixin


class BaseQueryHandler(Element, HandlerMixin, OptionsMixin):
    """Base Query Handler class that should be implemented by all Domain QueryHandlers.

    Query handlers process domain queries synchronously and return results.
    They are always associated with a Projection via ``part_of``.

    **Meta Options**

    | Option | Type | Description |
    |--------|------|-------------|
    | ``part_of`` | ``type`` | The projection this handler is associated with. Required. |

    Note:
        Query handlers are synchronous only. They have no stream category,
        no subscription configuration, and no UnitOfWork wrapping.

    Example::

        @domain.query_handler(part_of=OrderSummary)
        class OrderSummaryQueryHandler(BaseQueryHandler):
            @read(GetOrdersByCustomer)
            def get_by_customer(self, query):
                view = current_domain.view_for(OrderSummary)
                return view.query.filter(
                    customer_id=query.customer_id
                ).all()
    """

    element_type = DomainObjects.QUERY_HANDLER

    @classmethod
    def _default_options(cls) -> list[tuple[str, Optional[Union[str, dict]]]]:
        part_of = (
            getattr(cls.meta_, "part_of") if hasattr(cls.meta_, "part_of") else None
        )

        return [
            ("part_of", part_of),
        ]

    def __new__(cls, *args: Any, **kwargs: Any) -> "BaseQueryHandler":
        if cls is BaseQueryHandler:
            raise NotSupportedError("BaseQueryHandler cannot be instantiated")
        return super().__new__(cls)


_T = TypeVar("_T")


def query_handler_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
    element_cls = derive_element_class(element_cls, BaseQueryHandler, **opts)

    if not element_cls.meta_.part_of:
        raise IncorrectUsageError(
            f"Query Handler `{element_cls.__name__}` needs to be associated with a Projection"
        )

    return element_cls
