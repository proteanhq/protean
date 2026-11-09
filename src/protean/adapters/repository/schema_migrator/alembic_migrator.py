"""The ``SchemaMigrator`` of the SQLAlchemy providers, backed by Alembic."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from alembic.config import Config

from protean.adapters.repository.schema_migrator import (
    PROVIDER_ATTRIBUTE,
    write_migrations_folder,
)

if TYPE_CHECKING:
    from protean.adapters.repository.sqlalchemy import SAProvider


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

    def alembic_config(self) -> Config:
        """Alembic's configuration for the folder, carrying this provider.

        ``run_migrations`` uses the provider it carries instead of loading the
        domain again from ``alembic.ini``.
        """
        config = Config(str(self.directory / "alembic.ini"))
        config.attributes[PROVIDER_ATTRIBUTE] = self.provider
        return config
