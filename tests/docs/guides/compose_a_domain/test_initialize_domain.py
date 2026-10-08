"""The examples on the Initialize the domain guide behave as the page says."""

import pytest

from protean.utils.reflection import declared_fields
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_init_connects_the_default_provider():
    example = load_example("guides/compose-a-domain/initialize-domain/001.py")

    assert "default" in example.domain.providers
    assert example.domain.providers["default"].conn_info["provider"] == "memory"
    assert example.domain.registry.elements == {"aggregates": [example.User]}


def test_init_without_traversal_keeps_the_explicit_registration():
    example = load_example("guides/compose-a-domain/initialize-domain/002.py")

    assert example.domain.registry.elements == {"aggregates": [example.User]}


def test_registry_holds_the_aggregate_entity_and_event(capsys):
    example = load_example("guides/compose-a-domain/016.py")

    assert example.domain.registry.elements == {
        "aggregates": [example.User],
        "events": [example.Registered],
        "entities": [example.Credentials],
    }
    assert example.Credentials.meta_.part_of is example.User
    assert example.Registered.meta_.part_of is example.User
    assert "'aggregates': [<class" in capsys.readouterr().out

    example.domain.init(traverse=False)


def test_sqlite_database_becomes_the_default_provider(tmp_path, monkeypatch):
    # The example points at a relative ``test.db``, so keep it out of the repo.
    monkeypatch.chdir(tmp_path)

    example = load_example("guides/compose-a-domain/017.py")

    provider = example.domain.providers["default"]
    assert provider.conn_info["provider"] == "sqlite"
    assert provider.conn_info["database_uri"] == "sqlite:///test.db"


def test_init_resolves_a_part_of_given_as_a_string():
    example = load_example("guides/compose-a-domain/initialize-domain/003.py")
    assert example.Account.meta_.part_of == "User"

    example.domain.init(traverse=False)

    assert example.Account.meta_.part_of is example.User
    assert "user" in declared_fields(example.Account)
