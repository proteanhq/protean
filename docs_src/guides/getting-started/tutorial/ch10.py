# --8<-- [start:full]
# --8<-- [start:app_setup]
from fastapi import FastAPI
from pydantic import BaseModel

from protean.integrations.fastapi import (
    DomainContextMiddleware,
    register_exception_handlers,
)

from bookshelf import domain
from bookshelf.commands import AddBook, ConfirmOrder, PlaceOrder, ShipOrder
from bookshelf.projections import BookCatalog

domain.init()

app = FastAPI(title="Bookshelf API")

app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={"/": domain},
)
register_exception_handlers(app)
# --8<-- [end:app_setup]


# --8<-- [start:write_endpoints]
class AddBookRequest(BaseModel):
    title: str
    author: str
    isbn: str | None = None
    price_amount: float
    description: str | None = None


class PlaceOrderRequest(BaseModel):
    customer_name: str
    book_title: str
    quantity: int
    unit_price_amount: float


@app.post("/books")
def add_book(request: AddBookRequest):
    book_id = domain.process(
        AddBook(
            title=request.title,
            author=request.author,
            isbn=request.isbn,
            price_amount=request.price_amount,
            description=request.description,
        )
    )
    return {"book_id": str(book_id)}


@app.post("/orders")
def place_order(request: PlaceOrderRequest):
    order_id = domain.process(
        PlaceOrder(
            customer_name=request.customer_name,
            book_title=request.book_title,
            quantity=request.quantity,
            unit_price_amount=request.unit_price_amount,
        )
    )
    return {"order_id": str(order_id)}


@app.post("/orders/{order_id}/confirm")
def confirm_order(order_id: str):
    domain.process(ConfirmOrder(order_id=order_id))
    return {"status": "confirmed"}


@app.post("/orders/{order_id}/ship")
def ship_order(order_id: str):
    domain.process(ShipOrder(order_id=order_id))
    return {"status": "shipped"}


# --8<-- [end:write_endpoints]


# --8<-- [start:read_endpoints]
@app.get("/catalog")
def browse_catalog():
    results = domain.query_for(BookCatalog).all()
    return {
        "entries": [
            {
                "book_id": str(entry.book_id),
                "title": entry.title,
                "author": entry.author,
                "price": entry.price,
                "isbn": entry.isbn,
            }
            for entry in results.items
        ],
        "total": results.total,
    }


@app.get("/catalog/{book_id}")
def get_catalog_entry(book_id: str):
    entry = domain.repository_for(BookCatalog).get(book_id)
    return {
        "book_id": str(entry.book_id),
        "title": entry.title,
        "author": entry.author,
        "price": entry.price,
        "isbn": entry.isbn,
    }


# --8<-- [end:read_endpoints]
# --8<-- [end:full]
