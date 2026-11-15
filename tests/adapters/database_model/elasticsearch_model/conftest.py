import pytest

from tests.shared import initialize_domain, provider_adapter


@pytest.fixture
def test_domain():
    domain = initialize_domain(name="Elasticsearch Model Tests", root_path=__file__)

    with domain.domain_context():
        yield domain


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    domain = initialize_domain(name="Elasticsearch Model DB Setup", root_path=__file__)
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
        domain.register_database_model(
            ProviderCustomModel, part_of=Provider, schema_name="providers"
        )
        domain.init(traverse=False)

        provider_adapter(domain, "default").create_schema()

        yield

        provider_adapter(domain, "default").drop_schema()
