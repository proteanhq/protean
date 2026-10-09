from protean import Domain

# isort: split

# --8<-- [start:filter]
import logging

from protean.integrations.logging import ProteanCorrelationFilter

for handler in logging.getLogger().handlers:
    handler.addFilter(ProteanCorrelationFilter())
# --8<-- [end:filter]

domain = Domain(name="Embedded")
