from contextlib import asynccontextmanager

from fastapi import FastAPI

from protean import Domain
from protean.domain.context import has_domain_context
from protean.fields import String
from protean.integrations.fastapi import DomainContextMiddleware
from protean.utils.globals import current_domain

identity_domain = Domain(name="Identity")
catalogue_domain = Domain(name="Catalogue")


@identity_domain.aggregate
class Customer:
    name = String(required=True)


@catalogue_domain.aggregate
class Product:
    title = String(required=True)


# --8<-- [start:multi-domain]
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize all domains
    for d in [identity_domain, catalogue_domain]:
        d.init()
        with d.domain_context():
            d.setup_database()

    yield

    # Shutdown
    for d in [identity_domain, catalogue_domain]:
        with d.domain_context():
            pass  # Cleanup if needed


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={
        "/customers": identity_domain,
        "/products": catalogue_domain,
    },
)
# --8<-- [end:multi-domain]


@app.get("/{path:path}")
def active_domain(path: str) -> dict:
    return {"domain": current_domain.name if has_domain_context() else None}
