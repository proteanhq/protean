# --8<-- [start:imports]
from fastapi import FastAPI

from protean import Domain
from protean.integrations.fastapi.health import create_health_router

# --8<-- [end:imports]

domain = Domain(name="OrdersApi")

# --8<-- [start:health]
app = FastAPI()
app.include_router(create_health_router(domain))
# --8<-- [end:health]
