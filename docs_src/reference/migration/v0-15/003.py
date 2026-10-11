from protean import Domain

domain = Domain(name="Ordering")


# --8<-- [start:publish]
def publish_order_event(message_dict):
    domain.brokers["default"].publish("order_events", message_dict)


# --8<-- [end:publish]
