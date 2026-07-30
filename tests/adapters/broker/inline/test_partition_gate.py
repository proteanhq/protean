"""The partition-per-key port surface fails loud on a non-partitioning broker.

The inline broker does not advertise ``STREAM_PARTITIONING``, so every public
partition operation must raise ``NotSupportedError`` rather than silently drop
the ``sequential_by`` ordering guarantee (ADR-0028 decision 8).
"""

import pytest

from protean.adapters.broker.inline import InlineBroker
from protean.exceptions import NotSupportedError
from protean.port.broker import BrokerCapabilities


@pytest.fixture(autouse=True)
def init_domain(test_domain):
    test_domain.init(traverse=False)


@pytest.fixture
def broker(test_domain) -> InlineBroker:
    return InlineBroker("inline", test_domain, {})


def test_inline_broker_does_not_advertise_partitioning(broker: InlineBroker) -> None:
    assert not broker.has_capability(BrokerCapabilities.STREAM_PARTITIONING)


@pytest.mark.parametrize(
    "call",
    [
        lambda b: b.record_partition("cat", "a"),
        lambda b: b.partition_keys("cat"),
        lambda b: b.reap_partition("cat", "a", 0),
        lambda b: b.acquire_partition_lease("lease", "gen", "owner", 1000),
        lambda b: b.renew_partition_lease("lease", "owner:1", 1000),
        lambda b: b.release_partition_lease("lease", "owner:1"),
        lambda b: b.read_partition_fenced("s", "g", "c", "lease", "owner:1"),
        lambda b: b.ack_partition_fenced("s", "0-0", "g", "lease", "owner:1"),
        lambda b: b.reclaim_partition_pending("s", "g", "c"),
    ],
)
def test_partition_operations_raise_not_supported(broker: InlineBroker, call) -> None:
    with pytest.raises(NotSupportedError):
        call(broker)
