from fastapi import FastAPI

from protean import Domain
from protean.integrations.fastapi import instrument_app

domain = Domain(
    name="Orders",
    config={"telemetry": {"enabled": True, "exporter": "console"}},
)

app = FastAPI()

# --8<-- [start:options]
instrument_app(
    app,
    domain,
    excluded_urls="health,ready",  # Skip health check endpoints
)
# --8<-- [end:options]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict:
    return {"status": "ok"}


@app.get("/orders")
def list_orders() -> list:
    return []
