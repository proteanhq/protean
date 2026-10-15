"""How the MySQL and SQL Server providers report a missing default driver.

None of these tests connect: SQLAlchemy builds the engine without opening a
connection. The "driver missing" cases put ``None`` in ``sys.modules`` for the
driver, so both Protean's check and SQLAlchemy fail to import it whether or not
it is installed.
"""

import sys
import types

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


def halted(module: str) -> str:
    """The message Python gives for importing a module blocked in ``sys.modules``."""
    return f"import of {module} halted; None in sys.modules"


@pytest.fixture
def block(monkeypatch):
    """Make the named modules fail to import."""

    def _block(*names: str) -> None:
        for name in names:
            monkeypatch.setitem(sys.modules, name, None)

    return _block


@pytest.fixture
def fake_mysqlclient(monkeypatch):
    """Stand in for an installed mysqlclient, enough for SQLAlchemy to build an engine."""
    module = types.ModuleType("MySQLdb")
    module.paramstyle = "format"
    module.version_info = (2, 2, 0, "final", 0)
    module.__version__ = "2.2.0"
    monkeypatch.setitem(sys.modules, "MySQLdb", module)


def init_domain(provider: str, uri: str) -> None:
    domain = Domain(name="Driver check")
    domain.config["databases"]["default"] = {
        "provider": provider,
        "database_uri": uri,
    }
    domain.init(traverse=False)


def build(provider_cls, provider: str, uri: str, domain):
    return provider_cls(
        name="orders",
        domain=domain,
        conn_info={"provider": provider, "database_uri": uri},
    )


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
        [f"mysql+pymysql://{MYSQL_PARTS}", f"mariadb+pymysql://{MYSQL_PARTS}"],
    )
    def test_mysql_names_pymysql_and_its_extra(self, block, uri):
        block("pymysql")
        scheme = uri.split("://")[0]

        with pytest.raises(ConfigurationError) as exc:
            init_domain("mysql", uri)

        assert str(exc.value) == (
            f"Database 'default' uses a '{scheme}://' URL, but the 'pymysql' "
            f"driver cannot be imported ({halted('pymysql')}). Install it "
            f'with `pip install "protean[mysql]"`.'
        )

    @pytest.mark.parametrize(
        "scheme", ["mysql", "mariadb"], ids=["mysql-url", "mariadb-url"]
    )
    def test_mysql_without_a_driver_asks_for_pymysql_and_its_extra(self, block, scheme):
        block("pymysql", "MySQLdb")

        with pytest.raises(ConfigurationError) as exc:
            init_domain("mysql", f"{scheme}://{MYSQL_PARTS}")

        assert str(exc.value) == (
            f"Database 'default' uses a '{scheme}://' URL, which SQLAlchemy "
            f"connects through 'MySQLdb', and it cannot be imported "
            f"({halted('MySQLdb')}). Write '{scheme}+pymysql://' to use the "
            f"'pymysql' driver, and install it with "
            f'`pip install "protean[mysql]"`.'
        )

    def test_mysql_without_a_driver_fails_without_mysqlclient_even_with_pymysql(
        self, block
    ):
        """SQLAlchemy would not use PyMySQL for this URL, so PyMySQL does not help."""
        pytest.importorskip("pymysql")
        block("MySQLdb")

        with pytest.raises(ConfigurationError) as exc:
            init_domain("mysql", f"mysql://{MYSQL_PARTS}")

        assert "Write 'mysql+pymysql://'" in str(exc.value)

    @pytest.mark.parametrize(
        "uri", [f"mssql+pyodbc://{MSSQL_PARTS}", f"mssql://{MSSQL_PARTS}"]
    )
    def test_mssql_names_pyodbc_and_its_extra(self, block, uri):
        block("pyodbc")
        scheme = uri.split("://")[0]

        with pytest.raises(ConfigurationError) as exc:
            init_domain("mssql", uri)

        assert str(exc.value) == (
            f"Database 'default' uses a '{scheme}://' URL, but the 'pyodbc' "
            f"driver cannot be imported ({halted('pyodbc')}). Install it "
            f'with `pip install "protean[mssql]"`.'
        )

    def test_chains_the_import_error(self, block):
        block("pyodbc")

        with pytest.raises(ConfigurationError) as exc:
            init_domain("mssql", f"mssql+pyodbc://{MSSQL_PARTS}")

        assert isinstance(exc.value.__cause__, ModuleNotFoundError)
        assert str(exc.value.__cause__) == halted("pyodbc")


@pytest.mark.no_test_domain
class TestAlternativeDriverGoesToSqlalchemy:
    @pytest.mark.parametrize(
        "provider, uri, blocked",
        [
            ("mysql", f"mysql+mysqldb://{MYSQL_PARTS}", ("pymysql", "MySQLdb")),
            ("mssql", f"mssql+pymssql://{MSSQL_PARTS}", ("pyodbc", "pymssql")),
        ],
    )
    def test_the_error_is_sqlalchemys(self, block, provider, uri, blocked):
        block(*blocked)

        with pytest.raises(ImportError) as exc:
            init_domain(provider, uri)

        assert not isinstance(exc.value, ConfigurationError)
        assert str(exc.value) == halted(blocked[1])

    def test_a_scheme_with_an_empty_driver_is_not_checked(self, block):
        block("pymysql", "MySQLdb")

        with pytest.raises(Exception) as exc:
            init_domain("mysql", f"mysql+://{MYSQL_PARTS}")

        assert not isinstance(exc.value, ConfigurationError)
        assert "Can't load plugin: sqlalchemy.dialects:mysql." in str(exc.value)

    def test_another_backend_is_not_checked(self, block):
        block("pyodbc")

        assert (
            sa_module._require_default_driver(
                "orders",
                make_url("sqlite:///orders.db"),
                frozenset({"mssql"}),
                "pyodbc",
                "pyodbc",
            )
            is None
        )


class TestDriverPresent:
    def test_mysql_keeps_the_url_as_configured(self, test_domain):
        pytest.importorskip("pymysql")

        provider = build(
            MysqlProvider, "mysql", f"mysql+pymysql://{MYSQL_PARTS}", test_domain
        )

        assert provider._engine.dialect.driver == "pymysql"
        assert provider._engine.url.render_as_string(hide_password=False) == (
            f"mysql+pymysql://{MYSQL_PARTS}"
        )

    def test_mssql_keeps_the_url_as_configured(self, test_domain):
        pytest.importorskip("pyodbc")

        provider = build(
            MssqlProvider, "mssql", f"mssql+pyodbc://{MSSQL_PARTS}", test_domain
        )

        assert provider._engine.dialect.driver == "pyodbc"
        assert provider._engine.url.drivername == "mssql+pyodbc"

    @pytest.mark.parametrize(
        "scheme", ["mysql", "mariadb"], ids=["mysql-url", "mariadb-url"]
    )
    def test_mysql_without_a_driver_keeps_working_on_mysqlclient(
        self, test_domain, block, fake_mysqlclient, scheme
    ):
        block("pymysql")

        provider = build(
            MysqlProvider, "mysql", f"{scheme}://{MYSQL_PARTS}", test_domain
        )

        assert provider._engine.dialect.driver == "mysqldb"
        assert provider._engine.url.drivername == scheme
