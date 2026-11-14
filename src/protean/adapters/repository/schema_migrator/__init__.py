"""Schema migrations for the SQLAlchemy providers, run by Alembic.

This module imports nothing from Alembic, so ``write_migrations_folder`` works
where Alembic is not installed. ``run_migrations`` uses Alembic only when an
Alembic command has already imported it. The Alembic-backed ``SchemaMigrator``
lives in ``alembic_migrator``.
"""

from __future__ import annotations

import configparser
import contextlib
import os
import string
import sys
import threading
from collections.abc import Iterator
from importlib import resources
from logging.config import fileConfig
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from protean.exceptions import ConfigurationError, NoDomainException
from protean.port.provider import DatabaseCapabilities
from protean.utils.domain_discovery import derive_domain

if TYPE_CHECKING:
    from protean.adapters.repository.sqlalchemy import SAProvider
    from protean.domain import Domain
    from protean.port.provider import BaseProvider

__all__ = [
    "CHECK_ATTRIBUTE",
    "PROVIDER_ATTRIBUTE",
    "migration_provider",
    "run_migrations",
    "write_migrations_folder",
]

# The key in Alembic's ``Config.attributes`` under which a Protean command
# passes the provider to ``run_migrations``.
PROVIDER_ATTRIBUTE = "protean_provider"

# The key in Alembic's ``Config.attributes`` under which ``protean db check``
# passes a list. ``run_migrations`` then compares the database with the table
# definitions, adds one line per difference to the list, and runs no migration.
CHECK_ATTRIBUTE = "protean_check"

# The thread that is inside ``run_migrations``, or None.
_running_thread: int | None = None
_running_lock = threading.Lock()


def _template(name: str) -> str:
    return resources.files(__name__).joinpath("templates", name).read_text("utf-8")


def _root_option(directory: Path, project_root: Path) -> str:
    """The ``protean_root`` value: ``project_root`` relative to the ini's folder."""
    try:
        relative = os.path.relpath(project_root.resolve(), directory.resolve())
    except ValueError:
        # On Windows, a folder on another drive has no relative path.
        return str(project_root.resolve()).replace("%", "%%")
    return "%(here)s/" + Path(relative).as_posix().replace("%", "%%")


def write_migrations_folder(
    directory: Path,
    domain_path: str,
    provider_name: str,
    project_root: Path | None = None,
) -> None:
    """Write an empty migrations folder for one provider into ``directory``.

    The folder holds ``alembic.ini``, ``env.py``, ``script.py.mako`` and an
    empty ``versions/``. ``alembic.ini`` records ``domain_path``,
    ``provider_name`` and ``project_root`` (the current directory when not
    given), the folder a plain ``alembic`` run loads the domain from.
    ``directory`` and its parents are created when missing.

    Raises:
        ConfigurationError: ``directory`` exists and is not an empty folder, or
            the files cannot be written. Nothing is left behind in
            ``directory``.
    """
    _refuse_unusable(directory)

    # configparser reads ``%`` as the start of an interpolation, so a literal
    # ``%`` in a recorded value is written as ``%%``.
    ini = string.Template(_template("alembic.ini.tmpl")).substitute(
        domain=domain_path.replace("%", "%%"),
        provider=provider_name.replace("%", "%%"),
        root=_root_option(directory, project_root or Path.cwd()),
    )

    created: list[Path] = []
    try:
        if not directory.is_dir():
            _make_folder(directory, created)
        _make_folder(directory / "versions", created)
        _write_new(directory / "alembic.ini", ini, created)
        _write_new(directory / "env.py", _template("env.py.tmpl"), created)
        _write_new(directory / "script.py.mako", _template("script.py.mako"), created)
    except OSError as exc:
        # Remove a partial folder, so a second ``init`` does not refuse it as
        # not empty.
        _remove_created(created)
        raise ConfigurationError(
            f"Cannot create migrations in '{directory}': {exc.strerror or exc}."
        ) from exc


def _refuse_unusable(directory: Path) -> None:
    if directory.exists() and not directory.is_dir():
        raise ConfigurationError(
            f"Cannot create migrations in '{directory}': it exists and is not "
            "a folder. Choose another folder with --directory."
        )
    if directory.is_dir() and any(directory.iterdir()):
        raise ConfigurationError(
            f"Cannot create migrations in '{directory}': it already exists and "
            "is not empty. Choose another folder with --directory."
        )


# Another process can write into the folder after ``_refuse_unusable`` passed.
# The writer creates every path exclusively and records it, so a failed write
# removes only what it created and never another writer's files.


def _make_folder(path: Path, created: list[Path]) -> None:
    """Create ``path`` and its missing parents; raise if ``path`` exists."""
    if not path.parent.is_dir():
        _make_folder(path.parent, created)
    path.mkdir()
    created.append(path)


def _write_new(path: Path, text: str, created: list[Path]) -> None:
    """Write ``text`` to a new file; raise ``FileExistsError`` if it exists."""
    with path.open("x", encoding="utf-8") as file:
        created.append(path)
        file.write(text)


def _remove_created(created: list[Path]) -> None:
    for path in reversed(created):
        if path.is_dir():
            # A folder that another writer has added to stays.
            with contextlib.suppress(OSError):
                path.rmdir()
        else:
            path.unlink(missing_ok=True)


def _migrations_provider_name(directory: Path) -> str:
    """The name of the provider the migrations folder ``directory`` belongs to.

    Reads the ``protean_provider`` option that ``write_migrations_folder``
    records in ``alembic.ini``.

    Raises:
        ConfigurationError: ``directory`` has no ``alembic.ini``, or the file
            cannot be read or has no ``protean_provider`` option.
    """
    ini = directory / "alembic.ini"
    if not ini.is_file():
        raise ConfigurationError(
            f"No migrations found in '{directory}': it has no alembic.ini. "
            "Create them with `protean db init`, or name the folder with "
            "--directory."
        )
    parser = configparser.ConfigParser()
    try:
        # ``read_file`` and not ``read``, which skips a file it cannot open.
        with ini.open(encoding="utf-8") as file:
            parser.read_file(file)
        name = parser.get("alembic", "protean_provider", fallback="")
    except (configparser.Error, OSError, UnicodeDecodeError) as exc:
        raise ConfigurationError(f"Cannot read '{ini}': {exc}") from exc
    if not name:
        raise ConfigurationError(
            f"'{ini}' has no 'protean_provider' option in its [alembic] section."
        )
    return name


def migration_provider(domain: Domain, provider_name: str) -> BaseProvider:
    """Return the provider of ``domain`` that migrations run against.

    Raises:
        ConfigurationError: ``provider_name`` is not configured, the provider
            does not declare ``SCHEMA_MIGRATIONS``, or its ``managed`` setting
            is ``false``.
    """
    configured = sorted(domain.providers)
    if provider_name not in domain.providers:
        raise ConfigurationError(
            f"Provider '{provider_name}' is not configured. "
            f"Configured providers: {', '.join(configured)}."
        )

    provider = domain.providers[provider_name]
    if DatabaseCapabilities.SCHEMA_MIGRATIONS not in provider.capabilities:
        capable = [
            name
            for name in configured
            if DatabaseCapabilities.SCHEMA_MIGRATIONS
            in domain.providers[name].capabilities
        ]
        alternatives = (
            f"Providers that declare it: {', '.join(capable)}."
            if capable
            else "No configured provider declares it."
        )
        raise ConfigurationError(
            f"Provider '{provider_name}' ({provider.__database__}) does not "
            "support schema migrations. Migration commands need a provider "
            f"that declares SCHEMA_MIGRATIONS. {alternatives}"
        )

    if not provider.managed:
        raise ConfigurationError(
            f"Provider '{provider_name}' has managed = false, so Protean does not "
            "change its schema. Set managed = true to use migrations."
        )

    return provider


def run_migrations() -> None:
    """Run Alembic's migration environment for one Protean provider.

    Every ``env.py`` that ``write_migrations_folder`` writes calls this. A
    Protean command passes the provider in ``Config.attributes`` under
    ``PROVIDER_ATTRIBUTE``. A plain ``alembic`` run passes none, so the
    domain is loaded from the ``protean_domain`` option of ``alembic.ini``,
    from the ``protean_root`` folder, and the provider is the one
    ``protean_provider`` names. The provider passes the same checks as in
    ``migration_provider``.

    Migrations run on the provider's engine, or, in offline mode, render SQL
    for the provider's database URL. The target metadata is the provider's
    ``metadata``. When ``Config.attributes`` holds a list under
    ``CHECK_ATTRIBUTE`` and the run is online, no migration runs: the list
    receives the differences between the database and the metadata, and
    nothing is written to the database.

    Does nothing when no Alembic command is running, and when called again
    from the thread that is running it.

    Raises:
        ConfigurationError: ``alembic.ini`` names no domain or no provider, a
            domain that cannot be loaded, or a provider that fails the checks
            of ``migration_provider``; another thread is running it; or, in a
            check, the database is not at the latest migration.
    """
    # Domain traversal imports every module beside the domain file and in its
    # immediate subfolders, so a ``migrations/`` folder next to ``domain.py``
    # has its ``env.py`` imported while the domain loads. That happens outside
    # any Alembic run when a Protean command loads the domain, and inside a
    # run of another provider's folder (``migrations/analytics/``) when this
    # function loads it. Neither import may start a run, and the first must
    # not import Alembic.
    global _running_thread
    context: Any = sys.modules.get("alembic.context")
    # Alembic sets ``context.config`` only while it runs ``env.py``.
    config = getattr(context, "config", None)
    if config is None:
        return

    with _running_lock:
        if _running_thread == threading.get_ident():
            return
        if _running_thread is not None:
            raise ConfigurationError(
                "Another thread is running migrations in this process. Alembic "
                "runs one migration environment at a time."
            )
        _running_thread = threading.get_ident()
    try:
        provider: SAProvider | None = config.attributes.get(PROVIDER_ATTRIBUTE)
        if provider is not None:
            _run(context, provider)
        else:
            # The domain path and a relative SQLite URL are resolved from the
            # folder ``protean db init`` ran in, so ``alembic`` works from any
            # folder. That folder stays current for the whole run, because the
            # engine opens a relative SQLite file only when it connects.
            with _working_directory(config.get_main_option("protean_root")):
                _run(context, _provider_from_ini(config, context.is_offline_mode()))
    finally:
        _running_thread = None


def _ini_option(config: Any, name: str) -> str:
    value = config.get_main_option(name)
    if not value:
        raise ConfigurationError(
            f"'{config.config_file_name}' has no '{name}' option in its "
            "[alembic] section."
        )
    return cast("str", value)


@contextlib.contextmanager
def _working_directory(path: str | None) -> Iterator[None]:
    """Run the block in ``path``, the folder relative paths are resolved from."""
    if path is None:
        yield
        return
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _provider_from_ini(config: Any, offline: bool) -> SAProvider:
    """The provider that ``alembic.ini`` names, from the domain it names.

    When ``offline``, the domain opens no database connection.
    """
    # A plain ``alembic`` run sets up its own logging from ``alembic.ini``.
    if config.config_file_name is not None and config.file_config.has_section(
        "loggers"
    ):
        # The parsed file, because a relative ``-c`` path no longer resolves
        # once the run has changed to ``protean_root``.
        fileConfig(config.file_config, disable_existing_loggers=False)

    domain_path = _ini_option(config, "protean_domain")
    provider_name = _ini_option(config, "protean_provider")
    try:
        domain = derive_domain(domain_path)
    except NoDomainException as exc:
        raise ConfigurationError(
            f"The domain '{domain_path}' named in '{config.config_file_name}' "
            f"cannot be loaded: {exc.args[0]}"
        ) from exc
    # A non-empty path raises NoDomainException when nothing is found, so
    # derive_domain does not return None here.
    domain = cast("Domain", domain)
    domain._init(connect=not offline)
    return cast("SAProvider", migration_provider(domain, provider_name))


def _run(context: Any, provider: SAProvider) -> None:
    # Alembic is running, so the module that imports it can be imported.
    from protean.adapters.repository.schema_migrator.autogenerate import (  # noqa: PLC0415
        configure_options,
        differences,
        expression_index_warnings_hidden,
    )

    with provider.domain.domain_context():
        metadata = provider.metadata
        dialect_name = provider._engine.dialect.name
        if context.is_offline_mode():
            context.configure(
                url=provider._engine.url,
                literal_binds=True,
                dialect_opts={"paramstyle": "named"},
                **configure_options(metadata, dialect_name, None),
            )
            with context.begin_transaction():
                context.run_migrations()
            return

        found: list[str] | None = context.config.attributes.get(CHECK_ATTRIBUTE)
        with provider._engine.connect() as connection:
            context.configure(
                connection=connection,
                **configure_options(metadata, dialect_name, connection),
            )
            if found is not None:
                # No transaction is begun, so nothing is stamped, and the
                # connection rolls back what reflection opened when it closes.
                with expression_index_warnings_hidden():
                    found += differences(context, metadata)
                return
            with expression_index_warnings_hidden(), context.begin_transaction():
                context.run_migrations()
