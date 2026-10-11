# --8<-- [start:supervisor]
from protean.server.supervisor import Supervisor

supervisor = Supervisor("my_package.domain", num_workers=4, log_level="DEBUG")
# --8<-- [end:supervisor]
