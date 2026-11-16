"""``domain.init()`` and ``domain.check()`` check the ``database_type`` of
repositories and database models, and a repository or model registered after
``init()`` is checked as it registers.

A repository may name ``"ALL"`` and a database model may leave the option
unset. Any other value must equal the ``database_type`` of an adapter in the
databases registry.
"""

from collections.abc import Iterator

import pytest

from protean.adapters.database.memory import MemoryDatabase
from protean.exceptions import ConfigurationError
from protean.fields import String
from protean.infra.registry import databases


class CustomTypeDatabase(MemoryDatabase):
    database_type = "customdb"


class IntegerTypeDatabase(MemoryDatabase):
    database_type = 5  # type: ignore[assignment]


def __getattr__(name: str) -> object:
    # The registry reads an adapter class with ``getattr`` on its module, so
    # this stands in for an adapter module that raises a non-import error.
    if name == "ExplodingDatabase":
        raise RuntimeError("the adapter module is broken")
    raise AttributeError(name)


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
    databases.register("exploding", f"{__name__}.ExplodingDatabase")
    databases.register("integer", f"{__name__}.IntegerTypeDatabase")
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
            "registered database adapter provides. Use `ALL` or one of: "
        )
        accepted = message.rpartition("one of: ")[2].split(", ")
        assert {
            "customdb",
            "exploding",
            "integer",
            "memory",
            "postgresql",
            "uninstalled",
        } <= set(accepted)
        assert "5" not in accepted

    def test_a_built_in_type_whose_extra_is_missing_passes(
        self, test_domain, aggregate
    ):
        # Discovery marked done with only the memory adapter registered stands
        # in for an install where the SQLAlchemy entry points registered nothing.
        databases._discovered = True
        databases.register("memory", "protean.adapters.database.memory.MemoryDatabase")
        assert "postgresql" not in databases.list()

        @test_domain.repository(part_of=aggregate, database_type="postgresql")
        class AccountRepository:
            pass

        test_domain.init(traverse=False)

    def test_the_name_of_an_adapter_whose_module_raises_passes(
        self, test_domain, aggregate
    ):
        @test_domain.repository(part_of=aggregate, database_type="exploding")
        class AccountRepository:
            pass

        test_domain.init(traverse=False)

    def test_a_non_string_type_raises(self, test_domain, aggregate):
        @test_domain.repository(part_of=aggregate, database_type=["postgresql"])
        class AccountRepository:
            pass

        with pytest.raises(ConfigurationError) as exc:
            test_domain.init(traverse=False)

        assert exc.value.args[0].startswith(
            "`AccountRepository` declares database_type `['postgresql']`, which "
            "no registered database adapter provides."
        )

    def test_check_reports_an_unknown_type(self, test_domain, aggregate):
        @test_domain.repository(part_of=aggregate, database_type="postgress")
        class AccountRepository:
            pass

        report = test_domain.check(traverse=False)

        assert report["status"] == "fail"
        assert [error["element"] for error in report["errors"]] == [
            "_validate_database_types"
        ]
        assert report["errors"][0]["message"].startswith(
            "`AccountRepository` declares database_type `postgress`"
        )


class TestRegistrationAfterInit:
    def test_an_unknown_type_raises_and_does_not_register(self, test_domain, aggregate):
        test_domain.init(traverse=False)

        class AccountRepository:
            pass

        with pytest.raises(ConfigurationError) as exc:
            test_domain.repository(part_of=aggregate, database_type="nosuchdb")(
                AccountRepository
            )

        assert exc.value.args[0].startswith(
            "`AccountRepository` declares database_type `nosuchdb`"
        )
        assert test_domain.registry.repositories == {}

    def test_a_known_type_registers(self, test_domain, aggregate):
        test_domain.init(traverse=False)

        @test_domain.repository(part_of=aggregate, database_type="customdb")
        class AccountRepository:
            pass

        assert list(test_domain.registry.repositories) == [
            f"{__name__}.AccountRepository"
        ]

    def test_an_unknown_model_type_raises(self, test_domain, aggregate):
        test_domain.init(traverse=False)

        class AccountModel:
            pass

        with pytest.raises(ConfigurationError) as exc:
            test_domain.database_model(part_of=aggregate, database_type="nosuchdb")(
                AccountModel
            )

        assert exc.value.args[0].startswith(
            "`AccountModel` declares database_type `nosuchdb`, which no "
            "registered database adapter provides. Leave it unset or use one of: "
        )

    def test_an_unknown_type_registered_before_init_is_not_checked_at_registration(
        self, test_domain, aggregate
    ):
        @test_domain.repository(part_of=aggregate, database_type="nosuchdb")
        class AccountRepository:
            pass

        assert len(test_domain.registry.repositories) == 1


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
