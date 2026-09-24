"""Read and rewrite the inline broker's retry queue.

`nack` records the time a message next becomes eligible for redelivery. Tests
read that schedule to check the delay, and move it into the past to exercise
redelivery, instead of sleeping until it arrives.
"""

from protean.adapters.broker.inline import CONSUMER_GROUP_SEPARATOR


def retry_group_key(stream: str, consumer_group: str) -> str:
    return f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"


def _retry_queue(broker, stream: str, consumer_group: str) -> list:
    return broker._failed_messages[retry_group_key(stream, consumer_group)]


def scheduled_retry_time(broker, stream, consumer_group, identifier) -> float:
    queue = _retry_queue(broker, stream, consumer_group)
    times = [entry[3] for entry in queue if entry[0] == identifier]
    assert len(times) == 1, f"expected one queued retry, found {len(times)}"
    return times[0]


def make_retry_due(broker, stream, consumer_group, identifier) -> None:
    """Bring a queued retry forward instead of sleeping until it is due."""
    group_key = retry_group_key(stream, consumer_group)
    queue = _retry_queue(broker, stream, consumer_group)
    broker._failed_messages[group_key] = [
        (msg_id, msg, count, 0.0 if msg_id == identifier else due)
        for msg_id, msg, count, due in queue
    ]
