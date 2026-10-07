# --8<-- [start:domain]
import time

from protean import Domain
from protean.fields import String


def epoch_ms_id() -> int:
    return int(time.time() * 1000)


domain = Domain(
    name="Launches",
    config={
        "identity_strategy": "function",
        "identity_type": "integer",
    },
    identity_function=epoch_ms_id,
)


@domain.aggregate
class Event:
    name: String(max_length=100, required=True)


# --8<-- [end:domain]
