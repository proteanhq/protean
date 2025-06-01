import pytest
import tomllib

from protean.domain.config import Config2


@pytest.fixture
def config():
    # Load config from a TOML file present in the same folder as this test file
    with open("tests/config/domain.toml", "rb") as f:
        config = tomllib.load(f)

    yield config


def test_normalized_config_without_environment(config):
    assert config["debug"] is True
    assert config["secret_key"] == "tvTpk3PAfkGr5x9!2sFU%XpW7bR8cwKA"
    assert config["identity_strategy"] == "uuid"
    assert config["identity_type"] == "string"
    assert config["event_processing"] == "sync"
    assert config["command_processing"] == "sync"
    assert config["databases"]["default"]["provider"] == "memory"
    assert config["databases"]["memory"]["provider"] == "memory"
    assert config["brokers"]["default"]["provider"] == "inline"
    assert config["caches"]["default"]["provider"] == "memory"
    assert config["event_store"]["provider"] == "memory"
    assert config["custom"]["foo"] == "bar"


def test_normalized_config_with_staging_environment(config, monkeypatch):
    monkeypatch.setenv("PROTEAN_ENV", "staging")

    config = Config2._normalize_config(config)

    assert config["debug"] is True
    assert config["secret_key"] == "tvTpk3PAfkGr5x9!2sFU%XpW7bR8cwKA"
    assert config["identity_strategy"] == "uuid"
    assert config["identity_type"] == "string"
    assert config["event_processing"] == "async"
    assert config["command_processing"] == "sync"
    assert config["databases"]["default"]["provider"] == "sqlite"
    assert config["databases"]["memory"]["provider"] == "memory"
    assert config["brokers"]["default"]["provider"] == "redis_pubsub"
    assert config["caches"]["default"]["provider"] == "memory"
    assert config["event_store"]["provider"] == "memory"
    assert config["custom"]["foo"] == "qux"


def test_normalized_config_with_prod_environment(config, monkeypatch):
    monkeypatch.setenv("PROTEAN_ENV", "prod")

    config = Config2._normalize_config(config)

    assert config["debug"] is True
    assert config["secret_key"] == "tvTpk3PAfkGr5x9!2sFU%XpW7bR8cwKA"
    assert config["identity_strategy"] == "uuid"
    assert config["identity_type"] == "string"
    assert config["event_processing"] == "async"
    assert config["command_processing"] == "async"
    assert config["databases"]["default"]["provider"] == "postgresql"
    assert config["databases"]["memory"]["provider"] == "memory"
    assert config["brokers"]["default"]["provider"] == "redis_pubsub"
    assert config["caches"]["default"]["provider"] == "memory"
    assert config["event_store"]["provider"] == "message_db"
    assert config["custom"]["foo"] == "quux"
