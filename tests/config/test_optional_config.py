# Test that the optional config is loaded correctly into Domain object

from protean.domain import Domain


def test_domain_loads_config_from_toml_file():
    domain = Domain(name="dummy")
    config = domain.load_config()
    assert config["debug"] is True
    assert config["testing"] is True
    assert config["secret_key"] == "tvTpk3PAfkGr5x9!2sFU%XpW7bR8cwKA"
    assert config["custom"]["foo"] == "bar"


def test_domain_loads_config_from_dict():
    test_config = {
        "debug": False,
        "testing": False,
        "custom": {"test_key": "test_value"},
    }
    domain = Domain(name="dummy")
    config = domain.load_config(test_config)
    assert config["debug"] is False
    assert config["testing"] is False
    assert config["custom"]["test_key"] == "test_value"
    assert domain.test_key == "test_value"
