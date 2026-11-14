"""The ``SchemaMigrator`` of the SQLAlchemy providers, backed by Alembic."""

from __future__ import annotations

import contextlib
from argparse import Namespace
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import Script, ScriptDirectory
from alembic.util import CommandError
from sqlalchemy.exc import DBAPIError

from protean.adapters.repository.schema_migrator import (
    CHECK_ATTRIBUTE,
    PROVIDER_ATTRIBUTE,
    write_migrations_folder,
)
from protean.exceptions import ConfigurationError

if TYPE_CHECKING:
    from protean.adapters.repository.sqlalchemy import SAProvider


@contextlib.contextmanager
def _command_errors() -> Iterator[None]:
    """Raise an Alembic ``CommandError`` as ``ConfigurationError``, message unchanged."""
    try:
        yield
    except CommandError as exc:
        raise ConfigurationError(str(exc)) from exc


class AlembicSchemaMigrator:
    """Keeps one SQLAlchemy provider's schema history in an Alembic folder."""

    def __init__(self, directory: Path, provider: SAProvider) -> None:
        self.directory = directory
        self.provider = provider

    def init(self, domain_path: str) -> None:
        """Write the migrations folder for ``domain_path`` and this provider.

        Raises ``ConfigurationError`` when the folder exists and is not empty,
        and leaves it unchanged.
        """
        write_migrations_folder(self.directory, domain_path, self.provider.name)

    def migrate(self, message: str) -> Path | None:
        """Autogenerate a revision named by ``message``.

        Returns the path of the revision file, or None when autogenerate found
        no change and no file was written.

        Raises:
            ConfigurationError: Alembic reports an error, such as a database
                that is not at the latest revision.
        """
        config = self.alembic_config()
        # The caller reports the file; ``quiet`` stops Alembic reporting it too.
        config.cmd_opts = Namespace(quiet=True, x=None)
        with _command_errors():
            script = command.revision(config, message=message, autogenerate=True)
        # Alembic returns a list when the runner dropped the revision.
        if not isinstance(script, Script):
            return None
        return Path(script.path)

    def upgrade(self, revision: str = "head", sql: bool = False) -> None:
        """Upgrade the database to ``revision``, or print the SQL with ``sql``.

        Raises:
            ConfigurationError: Alembic reports an error, such as an unknown
                revision.
        """
        with _command_errors():
            command.upgrade(self.alembic_config(), revision, sql=sql)

    def downgrade(self, revision: str, sql: bool = False) -> None:
        """Downgrade the database to ``revision``, or print the SQL with ``sql``.

        Raises:
            ConfigurationError: Alembic reports an error, such as an offline
                downgrade without a ``<from>:<to>`` range.
        """
        with _command_errors():
            command.downgrade(self.alembic_config(), revision, sql=sql)

    def check(self) -> list[str]:
        """The differences between the database and the table definitions.

        Returns one line per difference, as ``add_column order.discount``, or
        an empty list when they agree. Writes nothing to the database.

        Raises:
            ConfigurationError: The database is not at the latest migration,
                it cannot be read, the migrations folder is broken, its
                ``env.py`` does not run Protean's migration environment, or
                Alembic reports an error.
        """
        config = self.alembic_config()
        config.attributes[CHECK_ATTRIBUTE] = None
        with _command_errors():
            try:
                script = ScriptDirectory.from_config(config)
                with EnvironmentContext(config, script, dont_mutate=True):
                    script.run_env()
            except (CommandError, ConfigurationError):
                raise
            except DBAPIError as exc:
                raise ConfigurationError(
                    f"Cannot read the database of provider "
                    f"'{self.provider.name}': {exc.orig}"
                ) from exc
            except Exception as exc:
                # Alembic raises plain errors for a broken folder: a revision
                # file that does not compile, a ``down_revision`` the folder
                # lacks, or a missing ``env.py``.
                raise ConfigurationError(
                    f"Cannot compare the database with the migrations in "
                    f"'{self.directory}': "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
        found: list[str] | None = config.attributes[CHECK_ATTRIBUTE]
        if found is None:
            raise ConfigurationError(
                f"The 'env.py' in '{self.directory}' did not run Protean's "
                "migration environment, so the database was not compared."
            )
        return found

    def alembic_config(self) -> Config:
        """Alembic's configuration for the folder, carrying this provider.

        ``run_migrations`` uses the provider it carries instead of loading the
        domain again from ``alembic.ini``.
        """
        config = Config(str(self.directory / "alembic.ini"))
        config.attributes[PROVIDER_ATTRIBUTE] = self.provider
        return config
