"""Fixture: typed query dispatch resolves the declared result type.

A query declares the type its handler returns by subscripting the base:
``BaseQuery[OrderSummary]``. ``domain.dispatch`` then resolves to that type at
the call site. A bare ``BaseQuery`` subclass keeps resolving to ``Any``, and so
does a decorator-only query, which a checker sees as a plain class because
``@domain.query`` returns the class it was handed.

Instances are built with ``cast`` on purpose: the point under test is how
``dispatch`` types its result from the query's *static* type, not how the
element decorator synthesizes ``__init__``. ``cast`` keeps the fixture free of
call-arg noise that differs between mypy and pyright.
"""

from typing import cast

from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.domain import Domain
from protean.fields import Identifier, String

domain = Domain(__file__, "TestDomain")


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    status = String(max_length=20)


@domain.query(part_of=OrderSummary)
class GetOrderSummary(BaseQuery[OrderSummary]):
    order_id = Identifier(required=True)


@domain.query(part_of=OrderSummary)
class GetAnything(BaseQuery):
    order_id = Identifier(required=True)


# A decorator-only query: ``@domain.query`` returns the class it was handed, so
# no checker sees BaseQuery in its MRO. It carries no fields because mypy and
# pyright disagree about how an unannotated field specifier reads on a plain
# class, which has nothing to do with how ``dispatch`` types its result.
@domain.query(part_of=OrderSummary)
class ListOrderSummaries:
    """A query with no filters."""


typed_query = cast(GetOrderSummary, ...)
untyped_query = cast(GetAnything, ...)
decorator_only_query = cast(ListOrderSummaries, ...)

# A typed query resolves to its declared result type.
reveal_type(domain.dispatch(typed_query))

# A bare (untyped) query keeps resolving to Any.
reveal_type(domain.dispatch(untyped_query))

# A decorator-only query still dispatches, and resolves to Any.
reveal_type(domain.dispatch(decorator_only_query))
