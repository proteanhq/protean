"""``domain.init()`` checks the ``database_type`` of repositories and models.

A repository may name ``"ALL"`` and a database model may leave the option
unset. Any other value must equal the ``database_type`` of an adapter in the
``protean.databases`` registry.
"""

from collections.abc import Iterator

import pytest

from protean.adapters.database.memory import MemoryDatabase
from protean.exceptions import ConfigurationError
from protean.fields import String
from protean.infra.registry import databases


class CustomTypeDatabase(MemoryDatabase):
    database_type = "customdb"


@pytest.fixture(autouse=True)
def registered_adapters() -> Iterator[None]:
    """Register a custom adapter and one whose module does not import.

    Entry-point discovery is left undone, so the check under test must load
    the built-in adapters itself. The registry is restored afterwards.
    """
    saved = databases.list()
    saved_discovered = databases._discovered
    databases.clear()
    databases._discovered = False
    databases.register("custom", f"{__name__}.CustomTypeDatabase")
    databases.register("uninstalled", "tests.no_such_module.UninstalledDatabase")
    yield
    databases.clear()
    for name, path in saved.items():
        databases._paths[name] = path
    databases._discovered = saved_discovered


@pytest.fixture
def aggregate(test_domain):
    @test_domain.aggregate
    class Account:
        name = String()

    return Account


class TestRepository:
    def test_all_passes(self, test_domain, aggregate):
        @test_domain.repository(part_of=aggregate)
        class AccountRepository:
            pass

        test_domain.init(traverse=False)

    def test_a_built_in_type_passes(self, test_domain, aggregate):
        @test_domain.repository(part_of=aggregate, database_type="postgresql")
        class AccountRepository:
            pass

        test_domain.init(traverse=False)

    def test_a_custom_adapter_type_passes(self, test_domain, aggregate):
        @test_domain.repository(part_of=aggregate, database_type="customdb")
        class AccountRepository:
            pass

        test_domain.init(traverse=False)

    def test_the_name_of_an_adapter_that_fails_to_load_passes(
        self, test_domain, aggregate
    ):
        @test_domain.repository(part_of=aggregate, database_type="uninstalled")
        class AccountRepository:
            pass

        test_domain.init(traverse=False)

    def test_an_unknown_type_raises(self, test_domain, aggregate):
        @test_domain.repository(part_of=aggregate, database_type="nosuchdb")
        class AccountRepository:
            pass

        with pytest.raises(ConfigurationError) as exc:
            test_domain.init(traverse=False)

        message = exc.value.args[0]
        assert message.startswith(
            "`AccountRepository` declares database_type `nosuchdb`, which no "
            "registered database adapter provides. Use one of: "
        )
        accepted = message.rpartition("Use one of: ")[2].split(", ")
        assert {"customdb", "memory", "postgresql", "uninstalled"} <= set(accepted)


class TestDatabaseModel:
    def test_an_unset_type_passes(self, test_domain, aggregate):
        @test_domain.database_model(part_of=aggregate)
        class AccountModel:
            pass

        test_domain.init(traverse=False)

    def test_a_custom_adapter_type_passes(self, test_domain, aggregate):
        @test_domain.database_model(part_of=aggregate, database_type="customdb")
        class AccountModel:
            pass

        test_domain.init(traverse=False)

    def test_an_unknown_type_raises(self, test_domain, aggregate):
        @test_domain.database_model(part_of=aggregate, database_type="nosuchdb")
        class AccountModel:
            pass

        with pytest.raises(ConfigurationError) as exc:
            test_domain.init(traverse=False)

        assert exc.value.args[0].startswith(
            "`AccountModel` declares database_type `nosuchdb`"
        )

    def test_all_raises_on_a_model(self, test_domain, aggregate):
        @test_domain.database_model(part_of=aggregate, database_type="ALL")
        class AccountModel:
            pass

        with pytest.raises(ConfigurationError) as exc:
            test_domain.init(traverse=False)

        assert exc.value.args[0].startswith(
            "`AccountModel` declares database_type `ALL`"
        )
