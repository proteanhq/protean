import protean
from protean import Domain
from protean.fields import String

domain = Domain(name="app")
domain.config["lint"] = {"check_adapter_calls": True}


# --8<-- [start:suppressed]
@domain.aggregate(suppress_checks=["ADAPTER_CALL_IN_DOMAIN"])
class Order:
    name = String(max_length=50)

    def provision(self):
        return protean.adapters.broker.inline.InlineBroker("default", None, {})


# --8<-- [end:suppressed]
