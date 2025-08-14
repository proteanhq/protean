import pytest

from tests.shared import initialize_domain


@pytest.fixture
def test_domain():
    domain = initialize_domain(
        name="SQLAlchemy MSSQL Repository Tests", root_path=__file__
    )

    with domain.domain_context():
        yield domain


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    domain = initialize_domain(
        name="SQLAlchemy MSSQL Repository DB Setup", root_path=__file__
    )
    with domain.domain_context():
        # Create all associated tables
        from .elements import MssqlTestEntity

        domain.register(MssqlTestEntity)
        domain.init(traverse=False)

        domain.repository_for(MssqlTestEntity)._dao

        default_provider = domain.providers["default"]
        default_provider._metadata.create_all(default_provider._engine)

        yield

        # Drop all tables at the end of test suite
        default_provider = domain.providers["default"]
        default_provider._metadata.drop_all(default_provider._engine)
