import pytest

from tests.shared import initialize_domain


@pytest.fixture
def test_domain():
    domain = initialize_domain(__file__, "Elasticsearch Model Tests")

    with domain.domain_context():
        yield domain


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    domain = initialize_domain(__file__, "Elasticsearch Model DB Setup")
    with domain.domain_context():
        # Create all indexes
        from .elements import (
            Alien,
            ComplexUser,
            Person,
            Provider,
            ProviderCustomModel,
            User,
        )

        domain.register(Person)
        domain.register(Alien)
        domain.register(User)
        domain.register(ComplexUser)
        domain.register(Provider)
        domain.register_model(ProviderCustomModel, entity_cls=Provider)

        domain.providers["default"]._create_database_artifacts()

        yield

        domain.providers["default"]._drop_database_artifacts()
