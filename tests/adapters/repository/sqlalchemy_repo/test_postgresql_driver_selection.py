"""How the PostgreSQL provider picks its driver from ``database_uri``.

None of these tests connect: SQLAlchemy builds the engine without opening a
connection, so the driver choice is visible on ``engine.dialect.driver``. The
"driver missing" cases replace the import check, since the dev environment
installs both drivers.
"""

import logging

import pytest

from protean import Domain
from protean.adapters.repository import sqlalchemy as sa_module
from protean.adapters.repository.sqlalchemy import PostgresqlProvider
from protean.exceptions import ConfigurationError

URI_PARTS = "postgres:secret@db.example.com:5432/orders?sslmode=require"


def build_provider(test_domain, uri: str) -> PostgresqlProvider:
    return PostgresqlProvider(
        name="orders",
        domain=test_domain,
        conn_info={"provider": "postgresql", "database_uri": uri},
    )


@pytest.fixture
def drivers_missing(monkeypatch):
    """Make the named drivers fail to import, the way a missing package does."""

    def _missing(*names: str) -> None:
        real = sa_module._postgresql_driver_import_error

        def fake(driver: str) -> ImportError | None:
            if driver in names:
                return ModuleNotFoundError(f"No module named '{driver}'")
            return real(driver)

        monkeypatch.setattr(sa_module, "_postgresql_driver_import_error", fake)

    return _missing


class TestDriverImportCheck:
    @pytest.mark.parametrize("driver", ["psycopg", "psycopg2"])
    def test_an_installed_driver_has_no_error(self, driver):
        assert sa_module._postgresql_driver_import_error(driver) is None

    def test_a_missing_module_returns_its_error(self):
        error = sa_module._postgresql_driver_import_error("protean_no_such_driver")

        assert isinstance(error, ModuleNotFoundError)

    def test_a_module_that_fails_to_load_returns_its_error(self, monkeypatch):
        """psycopg 3 without its binary package or a system libpq."""

        def fail(name: str) -> None:
            raise ImportError("no pq wrapper available")

        monkeypatch.setattr(sa_module.importlib, "import_module", fail)

        error = sa_module._postgresql_driver_import_error("psycopg")

        assert str(error) == "no pq wrapper available"


class TestPlainUrl:
    def test_uses_psycopg_3_when_it_imports(self, test_domain):
        provider = build_provider(test_domain, f"postgresql://{URI_PARTS}")

        assert provider._engine.dialect.driver == "psycopg"

    def test_falls_back_to_psycopg2_when_psycopg_3_does_not_import(
        self, test_domain, drivers_missing
    ):
        drivers_missing("psycopg")

        provider = build_provider(test_domain, f"postgresql://{URI_PARTS}")

        assert provider._engine.dialect.driver == "psycopg2"

    def test_keeps_credentials_host_and_query(self, test_domain):
        provider = build_provider(test_domain, f"postgresql://{URI_PARTS}")

        url = provider._engine.url
        assert url.drivername == "postgresql+psycopg"
        assert url.username == "postgres"
        assert url.password == "secret"
        assert url.host == "db.example.com"
        assert url.port == 5432
        assert url.database == "orders"
        assert url.query == {"sslmode": "require"}

    def test_names_both_extras_when_no_driver_imports(
        self, test_domain, drivers_missing
    ):
        drivers_missing("psycopg", "psycopg2")

        with pytest.raises(ConfigurationError) as exc:
            build_provider(test_domain, f"postgresql://{URI_PARTS}")

        message = str(exc.value)
        assert "Database 'orders'" in message
        assert "no PostgreSQL driver can be imported" in message
        assert 'pip install "protean[postgresql]"' in message
        assert 'pip install "protean[postgresql-psycopg2]"' in message

    def test_logs_the_driver_it_picked(self, test_domain, caplog):
        with caplog.at_level(logging.INFO, logger=sa_module.logger.name):
            build_provider(test_domain, f"postgresql://{URI_PARTS}")

        records = [
            r
            for r in caplog.records
            if r.msg == "repository.postgresql.driver_selected"
        ]
        assert len(records) == 1
        assert records[0].database == "orders"
        assert records[0].driver == "psycopg"


class TestUrlThatNamesItsDriver:
    @pytest.mark.parametrize("driver", ["psycopg", "psycopg2"])
    def test_uses_the_named_driver(self, test_domain, driver):
        provider = build_provider(test_domain, f"postgresql+{driver}://{URI_PARTS}")

        assert provider._engine.dialect.driver == driver

    def test_psycopg2_is_used_even_when_psycopg_3_is_installed(self, test_domain):
        provider = build_provider(test_domain, f"postgresql+psycopg2://{URI_PARTS}")

        assert provider._engine.dialect.driver == "psycopg2"

    @pytest.mark.parametrize(
        ("driver", "extra"),
        [
            ("psycopg", "protean[postgresql]"),
            ("psycopg2", "protean[postgresql-psycopg2]"),
        ],
    )
    def test_names_the_extra_when_the_driver_does_not_import(
        self, test_domain, drivers_missing, driver, extra
    ):
        drivers_missing(driver)

        with pytest.raises(ConfigurationError) as exc:
            build_provider(test_domain, f"postgresql+{driver}://{URI_PARTS}")

        message = str(exc.value)
        assert f"'postgresql+{driver}://'" in message
        assert f"the '{driver}' driver cannot be imported" in message
        assert f'pip install "{extra}"' in message

    def test_does_not_fall_back_when_the_named_driver_is_missing(
        self, test_domain, drivers_missing
    ):
        """An explicit psycopg2 URL fails rather than quietly moving to psycopg 3."""
        drivers_missing("psycopg2")

        with pytest.raises(ConfigurationError):
            build_provider(test_domain, f"postgresql+psycopg2://{URI_PARTS}")

    def test_an_unsupported_driver_goes_to_sqlalchemy_unchanged(
        self, test_domain, monkeypatch
    ):
        provider = build_provider(test_domain, f"postgresql://{URI_PARTS}")
        checked: list[str] = []
        monkeypatch.setattr(
            sa_module, "_postgresql_driver_import_error", checked.append
        )
        provider.conn_info["database_uri"] = f"postgresql+pg8000://{URI_PARTS}"

        assert provider._engine_url().drivername == "postgresql+pg8000"
        assert checked == []

    def test_does_not_log_a_driver_choice(self, test_domain, caplog):
        with caplog.at_level(logging.INFO, logger=sa_module.logger.name):
            build_provider(test_domain, f"postgresql+psycopg2://{URI_PARTS}")

        assert not [
            r
            for r in caplog.records
            if r.msg == "repository.postgresql.driver_selected"
        ]


@pytest.mark.no_test_domain
def test_a_missing_driver_fails_domain_init(drivers_missing):
    """The error surfaces at ``domain.init()``, before any connection attempt."""
    drivers_missing("psycopg", "psycopg2")
    domain = Domain(name="Driver check")
    domain.config["databases"]["default"] = {
        "provider": "postgresql",
        "database_uri": f"postgresql://{URI_PARTS}",
    }

    with pytest.raises(
        ConfigurationError, match="no PostgreSQL driver can be imported"
    ):
        domain.init(traverse=False)
