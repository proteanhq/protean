from fastapi import FastAPI

from protean.domain.context import has_domain_context
from protean.integrations.fastapi import DomainContextMiddleware
from protean.utils.globals import current_domain

# isort: split

# --8<-- [start:resolver]
from protean.domain import Domain


def resolve_domain(path: str) -> Domain | None:
    """Route /tenant-a/* and /tenant-b/* to separate domains."""
    if path.startswith("/tenant-a"):
        return tenant_a_domain
    if path.startswith("/tenant-b"):
        return tenant_b_domain
    return None  # No domain context for other paths


# --8<-- [end:resolver]

app = FastAPI()
tenant_a_domain = Domain(name="TenantA")
tenant_b_domain = Domain(name="TenantB")

# --8<-- [start:register]
app.add_middleware(
    DomainContextMiddleware,
    resolver=resolve_domain,
)
# --8<-- [end:register]


@app.get("/{path:path}")
def active_domain(path: str) -> dict:
    return {"domain": current_domain.name if has_domain_context() else None}
