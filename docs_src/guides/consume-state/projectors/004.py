# --8<-- [start:elements]
from protean import Domain, current_domain
from protean.core.projector import on
from protean.fields import Identifier, Integer, String

domain = Domain(name="Catalog")


@domain.aggregate
class Product:
    name: String(required=True)


@domain.event(part_of=Product)
class ReviewApproved:
    review_id: Identifier(required=True)
    product_id: Identifier(required=True)


@domain.projection
class ProductStats:
    product_id: Identifier(identifier=True)
    total_reviews: Integer(default=0)


# --8<-- [end:elements]


# --8<-- [start:projector]
@domain.projector(projector_for=ProductStats, aggregates=[Product], idempotent=True)
class RatingProjector:
    @on(ReviewApproved)
    def on_review_approved(self, event: ReviewApproved):
        repository = current_domain.repository_for(ProductStats)
        stats = repository.get(event.product_id)
        stats.total_reviews += 1  # applied exactly once per event
        repository.add(stats)


# --8<-- [end:projector]
