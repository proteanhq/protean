# --8<-- [start:full]
from protean import Domain
from protean.core.projector import on
from protean.core.queryset import ResultSet
from protean.core.view import ReadView
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


# --8<-- [start:filtering]
def filter_books() -> tuple[ResultSet, ResultSet]:
    catalog = domain.view_for(StorefrontView)

    # Exact match
    by_orwell = catalog.query.filter(author="George Orwell").all()

    # Multiple conditions (AND)
    cheap_orwell = catalog.query.filter(
        author="George Orwell",
        price__lte=15.00,
    ).all()
    return by_orwell, cheap_orwell


# --8<-- [end:filtering]
# --8<-- [start:excluding]
def exclude_unknown(catalog: ReadView) -> ResultSet:
    # Exclude specific values
    return catalog.query.exclude(author="Unknown").all()


# --8<-- [end:excluding]
# --8<-- [start:ordering]
def order_books(catalog: ReadView) -> tuple[ResultSet, ResultSet, ResultSet]:
    # Ascending
    cheapest_first = catalog.query.order_by("price").all()

    # Descending (prefix with -)
    dearest_first = catalog.query.order_by("-price").all()

    # Multiple fields
    by_author = catalog.query.order_by(["author", "-price"]).all()
    return cheapest_first, dearest_first, by_author


# --8<-- [end:ordering]
# --8<-- [start:pagination]
def paginate(catalog: ReadView) -> tuple[ResultSet, ResultSet]:
    # First page (10 items)
    page1 = catalog.query.limit(10).offset(0).all()
    print(page1.page)  # 1
    print(page1.page_size)  # 10 (alias for limit)
    print(page1.total_pages)  # total pages based on matching records
    print(page1.has_next)  # True if more pages exist

    # Second page
    page2 = catalog.query.limit(10).offset(10).all()
    print(page2.page)  # 2
    print(page2.has_prev)  # True
    return page1, page2


# --8<-- [end:pagination]
# --8<-- [start:chaining]
def cheapest_orwell_books(catalog: ReadView) -> ResultSet:
    return (
        catalog.query.filter(author="George Orwell")
        .exclude(price__gt=20.00)
        .order_by("-price")
        .limit(10)
        .all()
    )


# --8<-- [end:chaining]
# --8<-- [start:read_only]
from protean.exceptions import NotSupportedError


def try_to_write(catalog: ReadView) -> list[str]:
    blocked = []
    try:
        catalog.query.update(price=0)
    except NotSupportedError:
        blocked.append("update")
    try:
        catalog.query.delete()
    except NotSupportedError:
        blocked.append("delete")
    return blocked


# --8<-- [end:read_only]


# --8<-- [start:api_endpoints]
# bookshelf/api.py: enhanced storefront endpoint


# @app.get("/storefront")
def browse_storefront(
    author: str | None = None,
    in_stock: bool | None = None,
    sort: str = "title",
    limit: int = 20,
    offset: int = 0,
):
    qs = domain.view_for(StorefrontView).query

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
        "page": results.page,
        "page_size": results.page_size,
        "total_pages": results.total_pages,
    }


# --8<-- [end:api_endpoints]
# --8<-- [end:full]
