""""Module to test Domain object functionality"""
# Protean
from protean import Domain, Entity
from protean.core import field
from protean.core.entity import _EntityMetaclass
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
        @Entity
        class DummyDog:
            """Test class to check Domain Registration"""
            name = field.String(max_length=50)

        domain = Domain(__name__)
        assert domain.registry is not None
        assert 'DummyDog' in domain.registry._entities

    def test_init2(self):
        """Test that Domain object can be initialized successfully"""
        domain = Domain(__name__)
        assert domain is not None


class TestEntityDecorator:
    """Test construction of Entities through a decorator"""

    def test_init(self):
        """Test basic decorator"""
        @Entity
        class TheDog:
            name = field.String(required=True, unique=True, max_length=50)
            age = field.Integer(default=5)
            owner = field.String(required=True, max_length=15)

        assert type(TheDog) == _EntityMetaclass
