from fastapi import FastAPI

from protean import Domain
from protean.integrations.fastapi import DomainContextMiddleware

app = FastAPI()

# --8<-- [start:domain]
my_domain = Domain(name="Shop")
# --8<-- [end:domain]

# The same keys as the ``[logging.http]`` table in ``domain.toml``.
my_domain.config["logging"]["http"] = {
    "enabled": False,
    "exclude_paths": ["/api/healthz"],
    "log_request_headers": False,
}

# --8<-- [start:override]
app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={"/api": my_domain},
    emit_http_wide_event=True,
    exclude_paths=["/api/internal/ping"],
    log_request_headers=True,
)
# --8<-- [end:override]


@app.get("/api/{path:path}")
def catch_all(path: str) -> dict:
    return {"path": path}


default_app = FastAPI()
default_app.add_middleware(
    DomainContextMiddleware, route_domain_map={"/api": my_domain}
)
default_app.add_api_route("/api/{path:path}", catch_all)
