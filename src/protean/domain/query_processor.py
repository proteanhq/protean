"""Query dispatch logic extracted from the Domain class.

The ``QueryProcessor`` resolves query handlers and dispatches queries
to them, returning results synchronously.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from protean.exceptions import IncorrectUsageError
from protean.utils import DomainObjects, fqn

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class QueryProcessor:
    """Dispatch queries to their registered handlers.

    Instantiated once by ``Domain.__init__()`` and called by
    ``Domain.dispatch()`` to handle the read-side query lifecycle.
    """

    def __init__(self, domain: Domain) -> None:
        self._domain = domain

    def dispatch(self, query: Any) -> Any:
        """Dispatch a query to its registered QueryHandler and return results.

        This is the read-side counterpart of ``process()`` (which handles
        commands on the write side).  Unlike ``process()``, ``dispatch()``
        is always synchronous, never wraps in a ``UnitOfWork``, and always
        returns the handler's return value.

        Args:
            query: Query to dispatch (instance of a ``@domain.query``-decorated class).

        Returns:
            Any: Return value from the query handler method.

        Raises:
            IncorrectUsageError: If *query* is not a registered query or
                no handler is registered.
        """
        from protean.core.query import BaseQuery

        if not isinstance(query, BaseQuery):
            raise IncorrectUsageError(f"`{query.__class__.__name__}` is not a Query")

        if (
            fqn(query.__class__)
            not in self._domain.registry._elements[DomainObjects.QUERY.value]
        ):
            raise IncorrectUsageError(
                f"Query `{query.__class__.__name__}` is not registered "
                f"in domain {self._domain.name}"
            )

        handler_cls = self.handler_for(query)
        if handler_cls is None:
            raise IncorrectUsageError(
                f"No Query Handler registered for `{query.__class__.__name__}`"
            )

        tracer = self._domain.tracer
        with tracer.start_as_current_span("protean.query.dispatch") as span:
            span.set_attribute("protean.query.type", query.__class__.__type__)
            span.set_attribute("protean.handler.name", handler_cls.__name__)
            return handler_cls._handle(query)

    def handler_for(self, query: Any) -> type | None:
        """Find the QueryHandler class registered to handle *query*.

        Returns ``None`` when no handler is registered.
        """
        for _, record in self._domain.registry._elements[
            DomainObjects.QUERY_HANDLER.value
        ].items():
            if query.__class__.__type__ in record.cls._handlers:
                return record.cls
        return None
