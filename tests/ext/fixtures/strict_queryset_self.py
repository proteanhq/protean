"""Fixture: ``QuerySet`` chain methods keep the queryset's own type."""

from protean.domain import Domain
from protean.fields import Identifier, String

domain = Domain(name="Strict")


@domain.projection
class ProductCard:
    product_id: str = Identifier(identifier=True)
    category_id: str | None = String()


qs = domain.view_for(ProductCard).query
reveal_type(qs)  # R: ReadOnlyQuerySet
qs = qs.filter(category_id="c1")
reveal_type(qs.exclude(category_id="c2").order_by("product_id"))  # R: ReadOnlyQuerySet
reveal_type(qs.limit(10).offset(5).only("product_id"))  # R: ReadOnlyQuerySet
