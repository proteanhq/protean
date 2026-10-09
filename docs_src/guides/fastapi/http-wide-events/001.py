# --8<-- [start:enable-imports]
from fastapi import FastAPI

from protean import Domain
from protean.integrations.fastapi import DomainContextMiddleware

# --8<-- [end:enable-imports]
# isort: split

from protean.exceptions import InvalidStateError
from protean.integrations.fastapi import register_exception_handlers

# --8<-- [start:enable]
identity_domain = Domain(name="Identity")
catalogue_domain = Domain(name="Catalogue")

app = FastAPI()
app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={
        "/customers": identity_domain,
        "/products": catalogue_domain,
    },
)
# --8<-- [end:enable]

register_exception_handlers(app)


@app.get("/customers/{customer_id}")
def get_customer(customer_id: str) -> dict:
    return {"id": customer_id}


@app.post("/products/{product_id}/retire")
def retire_product(product_id: str) -> dict:
    raise InvalidStateError("Product is already retired")


@app.get("/products/{product_id}/price")
def get_price(product_id: str) -> dict:
    raise RuntimeError("price service is down")
