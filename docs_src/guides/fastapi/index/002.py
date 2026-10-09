from fastapi import FastAPI

from protean import Domain
from protean.domain.context import has_domain_context
from protean.integrations.fastapi import DomainContextMiddleware
from protean.utils.globals import current_domain

app = FastAPI()

# --8<-- [start:longest-prefix]
core_domain = Domain(name="Core")
v2_domain = Domain(name="V2")

app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={
        "/api": core_domain,
        "/api/v2": v2_domain,
    },
)
# --8<-- [end:longest-prefix]


@app.get("/{path:path}")
def active_domain(path: str) -> dict:
    return {"domain": current_domain.name if has_domain_context() else None}
