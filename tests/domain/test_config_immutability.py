import pytest

from protean import Domain
from protean.utils import IdentityStrategy


def test_that_default_config_is_immutable():
    with pytest.raises(TypeError):
        Domain.default_config["IDENTITY_STRATEGY"] = "FOO"


def test_that_config_is_unique_to_each_domain():
    domain1 = Domain()
    assert domain1.config["IDENTITY_STRATEGY"] == IdentityStrategy.UUID.value

    domain1.config["IDENTITY_STRATEGY"] = "FOO"

    domain2 = Domain()
    assert domain2.config["IDENTITY_STRATEGY"] == IdentityStrategy.UUID.value
