from protean.domain.context import has_domain_context
from protean.utils.globals import current_domain

# isort: split

# --8<-- [start:basic]
from fastapi import FastAPI

from protean import Domain
from protean.integrations.fastapi import DomainContextMiddleware

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
# --8<-- [end:basic]


@app.get("/{path:path}")
def active_domain(path: str) -> dict:
    return {"domain": current_domain.name if has_domain_context() else None}
