from fastapi import FastAPI

from protean import Domain
from protean.domain.context import has_domain_context
from protean.integrations.fastapi import DomainContextMiddleware
from protean.utils.globals import current_domain

app = FastAPI()

# --8<-- [start:single-domain]
my_domain = Domain(name="Shop")

app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={"/": my_domain},
)
# --8<-- [end:single-domain]


@app.get("/{path:path}")
def active_domain(path: str) -> dict:
    return {"domain": current_domain.name if has_domain_context() else None}
