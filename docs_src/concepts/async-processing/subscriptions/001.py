from protean import Domain

domain = Domain(name="ecommerce")


# --8<-- [start:subscriber]
@domain.subscriber(broker="default", stream="external_orders")
class ExternalOrderSubscriber:
    def __call__(self, payload: dict) -> None:
        # Process external order
        ...


# --8<-- [end:subscriber]
