from protean import Domain

domain = Domain(name="Partners")

# --8<-- [start:subscriber]
received = []


@domain.subscriber(broker="default", stream="external_events")
class ExternalEventSubscriber:
    def __call__(self, payload: dict) -> None:
        received.append(payload)


# --8<-- [end:subscriber]
