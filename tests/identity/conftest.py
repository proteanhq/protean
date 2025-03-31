import pytest

from protean.domain import Domain
from protean.utils import IdentityType


@pytest.fixture
def domain():
    return Domain(__file__, "Test")


@pytest.fixture
def test_domain_with_string_identity(domain):
    domain.config["identity_type"] = IdentityType.STRING.value

    with domain.domain_context():
        yield domain


@pytest.fixture
def test_domain_with_int_identity(domain):
    domain.config["identity_type"] = IdentityType.INTEGER.value

    with domain.domain_context():
        yield domain


@pytest.fixture
def test_domain_with_uuid_identity(domain):
    domain.config["identity_type"] = IdentityType.UUID.value

    with domain.domain_context():
        yield domain
