"""How the MySQL and SQL Server providers report a missing default driver.

None of these tests connect: SQLAlchemy builds the engine without opening a
connection. The "driver missing" cases replace the import check, so they hold
whether or not PyMySQL and pyodbc are installed.
"""

import pytest
from sqlalchemy.engine.url import make_url

from protean import Domain
from protean.adapters.repository import sqlalchemy as sa_module
from protean.adapters.repository.sqlalchemy import MssqlProvider, MysqlProvider
from protean.exceptions import ConfigurationError

MYSQL_PARTS = "root:secret@db.example.com:3306/orders"
MSSQL_PARTS = (
    "sa:secret@db.example.com:1433/orders?driver=ODBC+Driver+18+for+SQL+Server"
)


@pytest.fixture
def drivers_missing(monkeypatch):
    """Make the named drivers fail to import, and record every module checked."""
    checked: list[str] = []

    def _missing(*names: str) -> list[str]:
        real = sa_module._driver_import_error

        def fake(module: str) -> ImportError | None:
            checked.append(module)
            if module in names:
                return ModuleNotFoundError(f"No module named '{module}'")
            return real(module)

        monkeypatch.setattr(sa_module, "_driver_import_error", fake)
        return checked

    return _missing


def init_domain(provider: str, uri: str) -> None:
    domain = Domain(name="Driver check")
    domain.config["databases"]["default"] = {
        "provider": provider,
        "database_uri": uri,
    }
    domain.init(traverse=False)


class TestDriverImportCheck:
    def test_an_importable_module_has_no_error(self):
        assert sa_module._driver_import_error("json") is None

    def test_a_missing_module_returns_its_error(self):
        error = sa_module._driver_import_error("protean_no_such_driver")

        assert isinstance(error, ModuleNotFoundError)

    def test_a_module_that_fails_to_load_returns_its_error(self, monkeypatch):
        """pyodbc installed without the unixODBC system library."""

        def fail(name: str) -> None:
            raise ImportError("libodbc.so.2: cannot open shared object file")

        monkeypatch.setattr(sa_module.importlib, "import_module", fail)

        error = sa_module._driver_import_error("pyodbc")

        assert str(error) == "libodbc.so.2: cannot open shared object file"


@pytest.mark.no_test_domain
class TestMissingDriverFailsDomainInit:
    @pytest.mark.parametrize(
        "uri",
        [
            f"mysql+pymysql://{MYSQL_PARTS}",
            f"mysql://{MYSQL_PARTS}",
            f"mariadb+pymysql://{MYSQL_PARTS}",
        ],
    )
    def test_mysql_names_pymysql_and_its_extra(self, drivers_missing, uri):
        drivers_missing("pymysql")
        scheme = uri.split("://")[0]

        with pytest.raises(ConfigurationError) as exc:
            init_domain("mysql", uri)

        assert str(exc.value) == (
            f"Database 'default' uses a '{scheme}://' URL, but the 'pymysql' "
            f"driver cannot be imported (No module named 'pymysql'). Install it "
            f'with `pip install "protean[mysql]"`.'
        )

    @pytest.mark.parametrize(
        "uri", [f"mssql+pyodbc://{MSSQL_PARTS}", f"mssql://{MSSQL_PARTS}"]
    )
    def test_mssql_names_pyodbc_and_its_extra(self, drivers_missing, uri):
        drivers_missing("pyodbc")
        scheme = uri.split("://")[0]

        with pytest.raises(ConfigurationError) as exc:
            init_domain("mssql", uri)

        assert str(exc.value) == (
            f"Database 'default' uses a '{scheme}://' URL, but the 'pyodbc' "
            f"driver cannot be imported (No module named 'pyodbc'). Install it "
            f'with `pip install "protean[mssql]"`.'
        )

    def test_chains_the_import_error(self, drivers_missing):
        drivers_missing("pyodbc")

        with pytest.raises(ConfigurationError) as exc:
            init_domain("mssql", f"mssql+pyodbc://{MSSQL_PARTS}")

        assert isinstance(exc.value.__cause__, ModuleNotFoundError)
        assert str(exc.value.__cause__) == "No module named 'pyodbc'"


class TestAlternativeDriverGoesToSqlalchemy:
    @pytest.mark.parametrize(
        "uri, backends, driver",
        [
            (f"mysql+mysqldb://{MYSQL_PARTS}", sa_module._MYSQL_DIALECTS, "pymysql"),
            (
                f"mariadb+mariadbconnector://{MYSQL_PARTS}",
                sa_module._MYSQL_DIALECTS,
                "pymysql",
            ),
            (f"mssql+pymssql://{MSSQL_PARTS}", frozenset({"mssql"}), "pyodbc"),
            ("sqlite:///orders.db", frozenset({"mssql"}), "pyodbc"),
        ],
    )
    def test_skips_the_check(self, drivers_missing, uri, backends, driver):
        checked = drivers_missing(driver)

        sa_module._require_default_driver("orders", make_url(uri), backends, driver)

        assert checked == []


class TestDriverPresent:
    def test_mysql_keeps_the_url_as_configured(self, test_domain):
        pytest.importorskip("pymysql")

        provider = MysqlProvider(
            name="orders",
            domain=test_domain,
            conn_info={
                "provider": "mysql",
                "database_uri": f"mysql+pymysql://{MYSQL_PARTS}",
            },
        )

        assert provider._engine.dialect.driver == "pymysql"
        assert provider._engine.url.render_as_string(hide_password=False) == (
            f"mysql+pymysql://{MYSQL_PARTS}"
        )

    def test_mssql_keeps_the_url_as_configured(self, test_domain):
        pytest.importorskip("pyodbc")

        provider = MssqlProvider(
            name="orders",
            domain=test_domain,
            conn_info={
                "provider": "mssql",
                "database_uri": f"mssql+pyodbc://{MSSQL_PARTS}",
            },
        )

        assert provider._engine.dialect.driver == "pyodbc"
        assert provider._engine.url.drivername == "mssql+pyodbc"

    def test_mysql_without_a_driver_is_not_rewritten(self, test_domain):
        pytest.importorskip("pymysql")
        provider = MysqlProvider(
            name="orders",
            domain=test_domain,
            conn_info={
                "provider": "mysql",
                "database_uri": f"mysql+pymysql://{MYSQL_PARTS}",
            },
        )
        provider.conn_info["database_uri"] = f"mysql://{MYSQL_PARTS}"

        assert provider._engine_url().drivername == "mysql"
