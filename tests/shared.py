"""Shared utilities for tests"""

import contextlib
import os
import shutil
import stat
import sys
import tempfile
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from protean.domain import Domain


class FrozenClock:
    """A :class:`protean.utils.Clock` pinned to a fixed instant.

    Assign it to ``domain.clock`` to make deadline, lock, and retry-backoff
    boundaries deterministic — every ``now()`` returns the same instant until
    :meth:`advance` moves it forward. This exercises the injectable clock seam
    the same way production code does, with no monkeypatching of the module-level
    ``datetime``.
    """

    def __init__(self, instant: datetime) -> None:
        self._instant = instant

    def now(self) -> datetime:
        return self._instant

    def advance(self, delta: timedelta) -> None:
        """Move the frozen instant forward by ``delta``."""
        self._instant += delta


# ---------------------------------------------------------------------------
# Service ports for Protean's Docker development environment
#
# Non-standard ports (5-prefix) avoid clashing with other projects that use
# default ports on the same machine. When changing these, also update:
#   - docker-compose.yml
#   - .github/workflows/ci.yml
#   - tests/**/domain.toml  (static config files cannot import Python constants)
# ---------------------------------------------------------------------------
POSTGRES_PORT = 55432
MESSAGE_DB_PORT = 55433
REDIS_PORT = 56379
ELASTICSEARCH_PORT = 59200
MSSQL_PORT = 51433

# Pre-built connection URIs
POSTGRES_URI = f"postgresql://postgres:postgres@localhost:{POSTGRES_PORT}/postgres"
MESSAGE_DB_URI = f"postgresql://message_store@localhost:{MESSAGE_DB_PORT}/message_store?sslmode=disable"
REDIS_URI = f"redis://localhost:{REDIS_PORT}"
MSSQL_URI = (
    f"mssql+pyodbc://sa:Protean123!@localhost:{MSSQL_PORT}/master"
    "?driver=ODBC+Driver+18+for+SQL+Server"
    "&TrustServerCertificate=yes&Encrypt=yes&MARS_Connection=yes"
)
ELASTICSEARCH_URI: dict = {"hosts": [f"localhost:{ELASTICSEARCH_PORT}"]}


def initialize_domain(name="Tests", root_path=None):
    """Initialize a Protean Domain with configuration from a file"""
    domain = Domain(name=name, root_path=root_path)

    # We initialize and load default configuration into the domain here
    #   so that test cases that don't need explicit domain setup can
    #   still function.
    domain._initialize()

    return domain


def assert_str_is_uuid(value: str) -> None:
    """Assert that a string is a valid UUID"""
    try:
        UUID(value)
    except ValueError:
        pytest.fail("Invalid UUID")


def assert_int_is_uuid(value: int) -> None:
    """Assert that an integer is a valid UUID"""
    try:
        UUID(int=value)
    except ValueError:
        pytest.fail("Invalid UUID")


@contextlib.contextmanager
def isolated_filesystem() -> Iterator[str]:
    """Create a temporary directory and chdir into it for the duration.

    Replaces Click's ``CliRunner.isolated_filesystem`` context manager, which
    Typer 0.26 dropped when its test runner stopped subclassing Click's
    ``CliRunner``. The current working directory is restored and the temporary
    directory removed on exit.
    """
    cwd = os.getcwd()
    temp_dir = tempfile.mkdtemp()
    os.chdir(temp_dir)
    try:
        yield temp_dir
    finally:
        os.chdir(cwd)
        try:
            shutil.rmtree(temp_dir)
        except OSError:
            # An entry may have been made read-only during the test; make the
            # tree writable and retry once so cleanup is reliable rather than
            # silently skipped. A genuine failure then surfaces instead of being
            # swallowed.
            for root, dirs, files in os.walk(temp_dir):
                for name in (*dirs, *files):
                    with contextlib.suppress(OSError):
                        os.chmod(os.path.join(root, name), stat.S_IRWXU)
            shutil.rmtree(temp_dir)


def change_working_directory_to(path):
    """Change working directory to a specific test directory
    and add it to the Python path so that the test can import.

    The test directory is expected to be in `support/domains`.
    """
    test_path = (Path(__file__) / ".." / "support" / "domains" / path).resolve()

    os.chdir(test_path)
    sys.path.insert(0, str(test_path))


@contextlib.contextmanager
def module_unavailable(*names: str, reload: tuple[str, ...] = ()) -> Iterator[None]:
    """Simulate optional packages being uninstalled, then restore them.

    Each name in ``names`` (and its submodules) is removed from ``sys.modules``
    and the top-level name is set to ``None``. A subsequent ``import <name>`` then
    raises ``ModuleNotFoundError`` and ``importlib.util.find_spec(name)`` returns
    ``None``: the same type and spec result an uninstalled package produces (the
    error message differs, reading "None in sys.modules"), which is what the
    dependency guards key off. Names in ``reload`` are only evicted (not set to
    ``None``) so they re-execute on next import; use this for a Protean package
    that lazily imports an absent extra, so its ``__init__`` runs again and hits
    the missing import.

    Exercises the "optional dependency is missing" paths without touching the
    real environment; the original module table is restored on exit.
    """
    to_clear = {
        key
        for key in list(sys.modules)
        if any(key == n or key.startswith(f"{n}.") for n in (*names, *reload))
    }
    saved = {key: sys.modules[key] for key in to_clear}
    for key in to_clear:
        del sys.modules[key]
    for name in names:
        sys.modules[name] = None  # type: ignore[assignment]
    try:
        yield
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def has_key_or_attr(obj, name):
    try:
        return name in obj  # Works if obj is dict-like
    except TypeError:
        return hasattr(obj, name)


def get_value_from_key_or_attr(obj, name, default=None):
    """
    Retrieve a value from a dict or object by name.
    Returns `default` if key/attribute is missing.
    """
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
