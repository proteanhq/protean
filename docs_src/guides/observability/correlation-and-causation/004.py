from protean import Domain

# isort: split

# --8<-- [start:structlog]
import structlog

from protean.integrations.logging import protean_correlation_processor

structlog.configure(
    processors=[
        protean_correlation_processor,
        structlog.dev.ConsoleRenderer(),
    ]
)
# --8<-- [end:structlog]

domain = Domain(name="Shipping")
