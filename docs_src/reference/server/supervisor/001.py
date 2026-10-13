# --8<-- [start:construct]
from protean.server.supervisor import Supervisor

supervisor = Supervisor(
    domain_path="my_package.domain",
    num_workers=4,
    test_mode=False,
    log_level="INFO",
)
# --8<-- [end:construct]
