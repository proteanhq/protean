from protean import Domain
from protean.fields import Identifier

domain = Domain(name="ecommerce")


@domain.aggregate
class Order: ...


# --8<-- [start:multi_aggregate]
@domain.aggregate
class Customer: ...


@domain.aggregate
class Product: ...


@domain.projection
class SalesDashboard:
    dashboard_id: Identifier(identifier=True)


@domain.projector(
    projector_for=SalesDashboard,
    stream_categories=[
        Order.meta_.stream_category,  # "<domain>::order"
        Customer.meta_.stream_category,  # "<domain>::customer"
        Product.meta_.stream_category,  # "<domain>::product"
    ],
)
class SalesDashboardProjector:
    """Builds comprehensive sales view from multiple sources."""


# --8<-- [end:multi_aggregate]
