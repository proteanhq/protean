"""The partition-per-key operations fail loud on a non-partitioning broker.

The inline broker does not advertise ``STREAM_PARTITIONING``, so every
partition operation on the ``Broker`` service must raise ``NotSupportedError``
rather than silently drop the ``sequential_by`` ordering guarantee (ADR-0028
decision 8).
"""

import pytest

from protean.adapters.broker.inline import InlineBroker
from protean.exceptions import NotSupportedError
from protean.infra.broker import Broker
from protean.port.broker import BrokerCapabilities
from tests.infra.test_broker_partitioning import PARTITION_CALLS


@pytest.fixture(autouse=True)
def init_domain(test_domain):
    test_domain.init(traverse=False)


@pytest.fixture
def broker(test_domain) -> Broker:
    return Broker(InlineBroker("inline", test_domain, {}))


def test_inline_broker_does_not_advertise_partitioning(broker: Broker) -> None:
    assert BrokerCapabilities.STREAM_PARTITIONING not in broker.capabilities


@pytest.mark.parametrize(("operation", "args"), PARTITION_CALLS)
def test_partition_operations_raise_not_supported(
    broker: Broker, operation: str, args: tuple
) -> None:
    with pytest.raises(NotSupportedError) as exc:
        getattr(broker, operation)(*args)

    assert str(exc.value) == (
        "Broker inline does not advertise STREAM_PARTITIONING, required for "
        f"`{operation.lstrip('_')}` (ADR-0028)."
    )
