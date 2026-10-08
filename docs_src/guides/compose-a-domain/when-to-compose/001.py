# --8<-- [start:full]
from fastapi import FastAPI

from protean import Domain
from protean.fields import String
from protean.integrations.fastapi import (
    DomainContextMiddleware,
    register_exception_handlers,
)

domain = Domain(name="Tasks")


@domain.aggregate
class Task:
    title: String(max_length=200, required=True)


# Initialize the domain at module load time
domain.init(traverse=False)

app = FastAPI()

# Middleware pushes/pops domain context per request
app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={"/": domain},
)

# Map domain exceptions to HTTP status codes
register_exception_handlers(app)
# --8<-- [end:full]
