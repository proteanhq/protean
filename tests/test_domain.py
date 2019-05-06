""""Module to test Domain object functionality"""
from protean import Domain
from protean import DomainElement
from protean.core import field
from protean.core.entity import Entity
from protean.domain import _DomainRegistry


class TestDomainRegistry:

    def test_init(self):
        registry = _DomainRegistry()
        assert registry is not None

    def test_singleton(self):
        registry1 = _DomainRegistry()
        registry2 = _DomainRegistry()
        assert registry1 is registry2


class TestDomain:

    def test_init(self):
        """Test that Domain object can be initialized successfully"""
        domain = Domain(__name__)
        assert domain is not None

    def test_register(self):
        @DomainElement
        class DummyDog(Entity):
            """Test class to check Domain Registration"""
            name = field.String(max_length=50)

        domain = Domain(__name__)
        assert domain.registry is not None
        assert DummyDog in domain.registry.entities

    def test_init2(self):
        """Test that Domain object can be initialized successfully"""
        domain = Domain(__name__)
        assert domain is not None
