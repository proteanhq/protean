# --8<-- [start:full]
from protean import Domain
from protean.core.projector import on
from protean.fields import Boolean, Float, Identifier, Integer, String
from protean.utils.globals import current_domain

domain = Domain("bookshelf")
domain.config["event_processing"] = "sync"


@domain.aggregate
class Book:
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    isbn: String(max_length=13)
    price: Float(default=0.0)


@domain.aggregate
class Inventory:
    book_id: Identifier(required=True)
    title: String(max_length=200, required=True)
    quantity: Integer(default=0)


@domain.event(part_of=Book)
class BookAdded:
    book_id: Identifier(required=True)
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    price: Float()


@domain.event(part_of=Inventory)
class InventoryStocked:
    book_id: Identifier(required=True)
    title: String(max_length=200)
    quantity: Integer()


# --8<-- [start:projection]
@domain.projection
class StorefrontView:
    """Cross-aggregate projection combining Book and Inventory data."""

    book_id: Identifier(identifier=True, required=True)
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    price: Float()
    quantity: Integer(default=0)
    in_stock: Boolean(default=False)


# --8<-- [end:projection]


# --8<-- [start:projector]
@domain.projector(
    projector_for=StorefrontView,
    aggregates=[Book, Inventory],
)
class StorefrontProjector:
    """Maintains the StorefrontView from Book and Inventory events."""

    @on(BookAdded)
    def on_book_added(self, event: BookAdded):
        entry = StorefrontView(
            book_id=event.book_id,
            title=event.title,
            author=event.author,
            price=event.price,
            quantity=0,
            in_stock=False,
        )
        current_domain.repository_for(StorefrontView).add(entry)

    @on(InventoryStocked)
    def on_inventory_stocked(self, event: InventoryStocked):
        repo = current_domain.repository_for(StorefrontView)
        try:
            entry = repo.get(event.book_id)
            entry.quantity = event.quantity
            entry.in_stock = event.quantity > 0
            repo.add(entry)
        except Exception:
            pass  # Book not yet in storefront


# --8<-- [end:projector]


domain.init(traverse=False)


# --8<-- [start:api_endpoints]
# bookshelf/api.py — enhanced storefront endpoint


# @app.get("/storefront")
def browse_storefront(
    author: str = None,
    in_stock: bool = None,
    sort: str = "title",
    limit: int = 20,
    offset: int = 0,
):
    qs = domain.query_for(StorefrontView)

    if author:
        qs = qs.filter(author=author)
    if in_stock is not None:
        qs = qs.filter(in_stock=in_stock)

    qs = qs.order_by(sort).limit(limit).offset(offset)
    results = qs.all()

    return {
        "entries": [
            {
                "book_id": str(e.book_id),
                "title": e.title,
                "author": e.author,
                "price": e.price,
                "quantity": e.quantity,
                "in_stock": e.in_stock,
            }
            for e in results.items
        ],
        "total": results.total,
    }


# --8<-- [end:api_endpoints]
# --8<-- [end:full]
