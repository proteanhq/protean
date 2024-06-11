import pytest

from protean import Domain, BaseAggregate
from protean.exceptions import ConfigurationError
from protean.fields import Auto


def test_invalid_identity_strategy():
    domain = Domain(__file__, load_toml=False)
    domain.config["identity_strategy"] = "invalid"

    class AutoTest(BaseAggregate):
        auto_field = Auto(identifier=True)

    domain.register(AutoTest)
    domain.init(traverse=False)
    with domain.domain_context():
        with pytest.raises(ConfigurationError) as exc:
            AutoTest()

        assert "Unknown Identity Strategy" in str(exc.value)


def test_error_on_no_identity_function_if_strategy_is_function():
    domain = Domain(__file__, load_toml=False)
    domain.config["identity_strategy"] = "function"

    class AutoTest(BaseAggregate):
        auto_field = Auto(identifier=True)

    domain.register(AutoTest)
    with pytest.raises(ConfigurationError) as exc:
        domain.init(traverse=False)

    assert "no Identity Function is provided" in exc.value.args[0]["element"]
