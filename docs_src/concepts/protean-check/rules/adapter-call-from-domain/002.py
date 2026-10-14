from protean import Domain
from protean.fields import String

domain = Domain(name="app")
domain.config["lint"] = {"check_adapter_calls": True}


# --8<-- [start:compliant]
@domain.aggregate
class Order:
    name = String(max_length=50)

    def total(self):
        return self._dao.filter(name="x")  # self-rooted -> no finding


# --8<-- [end:compliant]
