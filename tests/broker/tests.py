# Protean
import pytest

from protean.core.broker.base import BaseBroker
from protean.impl.broker.memory_broker import MemoryBroker


class TestBroker:
    def test_that_base_broker_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseBroker()

    def test_that_a_concrete_broker_can_be_initialized_successfully(self, test_domain):
        broker = MemoryBroker("dummy_name", test_domain, {})

        assert broker is not None

    def test_that_domain_initializes_broker_from_config(self, test_domain):
        assert test_domain.brokers_list is not None
        assert len(list(test_domain.brokers_list)) == 1
        assert isinstance(list(test_domain.brokers_list)[0], MemoryBroker)
