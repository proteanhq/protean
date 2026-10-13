# --8<-- [start:log-method-call]
from protean.utils.logging import log_method_call


class PlaceOrderHandler:
    @log_method_call
    def handle(self, command): ...


# --8<-- [end:log-method-call]
