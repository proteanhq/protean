# --8<-- [start:flask-imports]
# Flask example
from flask import Flask, g

# --8<-- [end:flask-imports]
# isort: split

from protean import Domain
from protean.domain.context import has_domain_context
from protean.utils.globals import current_domain

domain = Domain(name="Ordering")

# --8<-- [start:flask]
app = Flask(__name__)


@app.before_request
def push_domain_context() -> None:
    ctx = domain.domain_context()
    ctx.push()
    g.domain_ctx = ctx


@app.teardown_request
def pop_domain_context(exc: Exception | None) -> None:
    if hasattr(g, "domain_ctx"):
        g.domain_ctx.pop(exc)


# --8<-- [end:flask]


@app.get("/whoami")
def active_domain() -> dict:
    return {"domain": current_domain.name if has_domain_context() else None}
