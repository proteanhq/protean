import pytest

from tests.shared import initialize_domain, provider_adapter


@pytest.fixture
def test_domain():
    domain = initialize_domain(
        name="Elasticsearch Repository Tests", root_path=__file__
    )

    with domain.domain_context():
        yield domain


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    domain = initialize_domain(
        name="Elasticsearch Repository DB Setup", root_path=__file__
    )

    with domain.domain_context():
        # Create all indexes
        from .elements import Alien, ComplexUser, Person, User
        from .test_field_type_detection import DummyEntity, MinimalEntity, NumericEntity

        domain.register(Person)
        domain.register(Alien)
        domain.register(User)
        domain.register(ComplexUser)
        domain.register(DummyEntity)
        domain.register(MinimalEntity)
        domain.register(NumericEntity)
        domain.init(traverse=False)

        provider_adapter(domain, "default").create_schema()

        yield

        provider_adapter(domain, "default").drop_schema()
