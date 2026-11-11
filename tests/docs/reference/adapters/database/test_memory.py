"""Run the example on ``docs/reference/adapters/database/memory.md``."""

import tomllib

import pytest

from protean.adapters.repository.memory import MemoryProvider
from protean.adapters.repository.sqlalchemy import PostgresqlProvider
from protean.exceptions import ConfigurationError
from tests.docs.support import DOCS, DOCS_SRC, domain_from_config, load_example
from tests.shared import POSTGRES_PORT, POSTGRES_URI
from tests.support.snippets import expand_includes, extract_toml_blocks

pytestmark = pytest.mark.no_test_domain


def test_raw_query_applies_every_criterion():
    example = load_example("adapters/database/memory/001.py")

    # Tim is too young and Lin is inactive
    assert [row["name"] for row in example.results] == ["Ada"]
    assert example.results[0]["age"] == 36
    assert example.results[0]["status"] == "active"


def test_every_configuration_block_parses_as_toml():
    text = expand_includes(
        (DOCS / "reference/adapters/database/memory.md").read_text(), [DOCS_SRC]
    )
    blocks = [block for block in extract_toml_blocks(text) if not block.fragment]

    assert blocks
    for block in blocks:
        tomllib.loads(block.source)


@pytest.mark.parametrize(
    "path",
    [
        "adapters/database/memory/configuration.toml",
        "adapters/database/memory/development.toml",
    ],
)
def test_configuration_shown_builds_a_memory_provider(path, tmp_path):
    domain = domain_from_config(path, tmp_path)
    domain.init(traverse=False)

    assert type(domain.providers["default"]) is MemoryProvider


@pytest.mark.parametrize(
    "path",
    [
        "adapters/database/memory/configuration.toml",
        "adapters/database/memory/development.toml",
    ],
)
def test_changed_memory_provider_is_read(path, tmp_path):
    # The memory provider is also the default, so an unknown name shows the
    # key is read.
    text = (DOCS_SRC / path).read_text()
    assert 'provider = "memory"' in text
    text = text.replace('provider = "memory"', 'provider = "nosuch"')
    domain = domain_from_config(path, tmp_path, text=text)

    with pytest.raises(ConfigurationError, match="Unknown database provider 'nosuch'"):
        domain.init(traverse=False)


@pytest.mark.postgresql
def test_production_configuration_builds_a_postgresql_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", POSTGRES_URI)
    domain = domain_from_config("adapters/database/memory/production.toml", tmp_path)
    domain.init(traverse=False)

    provider = domain.providers["default"]
    assert type(provider) is PostgresqlProvider
    url = provider._engine.url
    assert (url.host, url.port, url.database) == (
        "localhost",
        POSTGRES_PORT,
        "postgres",
    )


def test_production_configuration_defaults_to_the_documented_uri(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    domain = domain_from_config("adapters/database/memory/production.toml", tmp_path)

    assert (
        domain.config["databases"]["default"]["database_uri"]
        == "postgresql://user:pass@db.example.com:5432/myapp"
    )
