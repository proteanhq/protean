# --8<-- [start:flagged]
import protean
from protean import Domain
from protean.fields import String

domain = Domain(name="app")


@domain.aggregate
class Order:
    name = String(max_length=50)

    def provision(self):
        # calls protean.adapters.* -> ADAPTER_CALL_IN_DOMAIN
        return protean.adapters.broker.inline.InlineBroker("default", None, {})


# --8<-- [end:flagged]


domain.config["lint"] = {"check_adapter_calls": True}
