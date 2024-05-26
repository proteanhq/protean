import pytest

from protean import Domain
from protean.utils import IdentityStrategy


def test_that_default_config_is_immutable():
    with pytest.raises(TypeError):
        Domain.default_config["identity_strategy"] = "FOO"


def test_that_config_is_unique_to_each_domain():
    domain1 = Domain(__file__, load_toml=False)
    assert domain1.config["identity_strategy"] == IdentityStrategy.UUID.value

    domain1.config["identity_strategy"] = "FOO"

    domain2 = Domain(__file__, load_toml=False)
    assert domain2.config["identity_strategy"] == IdentityStrategy.UUID.value
