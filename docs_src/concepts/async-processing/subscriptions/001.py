from protean import Domain

domain = Domain(name="ecommerce")


# --8<-- [start:subscriber]
external_orders = []


@domain.subscriber(broker="default", stream="external_orders")
class ExternalOrderSubscriber:
    def __call__(self, payload: dict) -> None:
        external_orders.append(payload)


# --8<-- [end:subscriber]
