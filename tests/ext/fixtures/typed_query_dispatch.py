"""Fixture: typed query dispatch resolves the declared result type.

A query declares the type its handler returns by subscripting the base:
``BaseQuery[OrderSummary]``. ``domain.dispatch`` then resolves to that type at
the call site. A bare ``BaseQuery`` subclass keeps resolving to ``Any``.

Instances are built with ``cast`` on purpose: the point under test is how
``dispatch`` types its result from the query's *static* type, not how the
element decorator synthesizes ``__init__``. ``cast`` keeps the fixture free of
call-arg noise that differs between mypy (with the plugin) and pyright (without
it).
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


typed_query = cast(GetOrderSummary, ...)
untyped_query = cast(GetAnything, ...)

# A typed query resolves to its declared result type.
reveal_type(domain.dispatch(typed_query))

# A bare (untyped) query keeps resolving to Any.
reveal_type(domain.dispatch(untyped_query))
