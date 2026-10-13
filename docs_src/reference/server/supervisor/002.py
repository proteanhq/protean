from protean.server.supervisor import Supervisor

# --8<-- [start:debug_logging]
from protean.utils.logging import configure_logging

configure_logging(level="DEBUG")
supervisor = Supervisor("my_package.domain", num_workers=4, log_level="DEBUG")
# --8<-- [end:debug_logging]
