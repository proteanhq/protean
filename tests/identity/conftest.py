import pytest

from protean.utils import IdentityType


@pytest.fixture
def test_domain_with_string_identity():
    from protean.domain import Domain

    domain = Domain(__file__, "Test")
    domain.config["IDENTITY_TYPE"] = IdentityType.STRING.value

    with domain.domain_context():
        yield domain


@pytest.fixture
def test_domain_with_int_identity():
    from protean.domain import Domain

    domain = Domain(__file__, "Test")
    domain.config["IDENTITY_TYPE"] = IdentityType.INTEGER.value

    with domain.domain_context():
        yield domain


@pytest.fixture
def test_domain_with_uuid_identity():
    from protean.domain import Domain

    domain = Domain(__file__, "Test")
    domain.config["IDENTITY_TYPE"] = IdentityType.UUID.value

    with domain.domain_context():
        yield domain
