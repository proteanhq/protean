# --8<-- [start:projection]
from protean import Domain
from protean.fields import (
    DateTime,
    Float,
    Identifier,
    Integer,
    String,
    Text,
    ValueObject,
)

domain = Domain(name="Inventory")


@domain.projection
class ProductInventory:
    """Projection for product inventory data optimized for querying."""

    product_id: Identifier(identifier=True, required=True)
    name: String(max_length=100, required=True)
    description: Text(required=True)
    price: Float(required=True)
    stock_quantity: Integer(default=0)
    last_updated: DateTime()


# --8<-- [end:projection]


# --8<-- [start:limit]
# Override the default limit on the projection
@domain.projection(limit=500)
class LargeReport:
    report_id = Identifier(identifier=True)
    title = String(max_length=200)


# Or override per-query
view = domain.view_for(LargeReport)
results = view.query.limit(1000).all()
# --8<-- [end:limit]


# --8<-- [start:value-object-field]
@domain.value_object
class Address:
    street = String(max_length=100)
    city = String(max_length=50)


@domain.projection
class OrderSummary:
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)
    total_amount = Float()
    shipping_address = ValueObject(Address)  # Stored as shipping_address_street, etc.


# --8<-- [end:value-object-field]


# --8<-- [start:shadow-field-query]
results = (
    domain.view_for(OrderSummary)
    .query.filter(shipping_address_city="Springfield")
    .all()
)
# --8<-- [end:shadow-field-query]


# --8<-- [start:query]
domain.init(traverse=False)

# A record that a projector has already written
with domain.domain_context():
    domain.repository_for(ProductInventory).add(
        ProductInventory(
            product_id="abc-123",
            name="Keyboard",
            description="Mechanical keyboard",
            price=89.0,
            stock_quantity=4,
        )
    )

view = domain.view_for(ProductInventory)

# Single lookup by identifier
item = view.get("abc-123")

# Fluent filtering via ReadOnlyQuerySet
results = view.query.filter(stock_quantity__lt=10).order_by("name").all()

for item in results:
    print(f"{item.name}: {item.stock_quantity} remaining")

# Convenience single-item lookup by criteria
item = view.find_by(product_id="abc-123")

# Total count and existence checks
total = view.count()
found = view.exists("abc-123")
# --8<-- [end:query]


# --8<-- [start:pagination]
page = view.query.order_by("name").limit(20).offset(40).all()

items = page.items  # The actual result items
total = page.total  # Total matching records across all pages
has_next = page.has_next  # True if more pages exist
has_prev = page.has_prev  # True if previous pages exist
number = page.page  # Current page number
page_size = page.page_size  # Items per page
total_pages = page.total_pages  # Total number of pages
# --8<-- [end:pagination]


# --8<-- [start:write]
with domain.domain_context():
    repo = domain.repository_for(ProductInventory)
    inventory_record = ProductInventory(
        product_id="def-456",
        name="Mouse",
        description="Wireless mouse",
        price=25.0,
        stock_quantity=12,
    )
    repo.add(inventory_record)
# --8<-- [end:write]


# --8<-- [start:connection]
conn = domain.connection_for(OrderSummary)
# conn is the raw SQLAlchemy session, Elasticsearch client,
# Redis client, etc., depending on the projection's backing store
# --8<-- [end:connection]
