from fastapi import FastAPI

from protean import Domain
from protean.integrations.fastapi import instrument_app

domain = Domain(
    name="Orders",
    config={"telemetry": {"enabled": True, "exporter": "console"}},
)

app = FastAPI()

# --8<-- [start:observatory]
instrument_app(app, domain, excluded_urls="metrics,stream,api/health")
# --8<-- [end:observatory]


@app.get("/metrics")
def metrics() -> str:
    return ""


@app.get("/api/health")
def api_health() -> dict:
    return {"status": "ok"}


@app.get("/api/orders")
def list_orders() -> list:
    return []
