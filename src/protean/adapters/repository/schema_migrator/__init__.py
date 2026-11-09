"""Schema migrations for the SQLAlchemy providers, run by Alembic.

This module imports nothing from Alembic, so ``write_migrations_folder`` works
where Alembic is not installed. ``run_migrations`` imports Alembic when it is
called. The Alembic-backed ``SchemaMigrator`` lives in ``alembic_migrator``.
"""

from __future__ import annotations

import string
from importlib import resources
from logging.config import fileConfig
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from protean.exceptions import ConfigurationError
from protean.utils.domain_discovery import derive_domain

if TYPE_CHECKING:
    from protean.adapters.repository.sqlalchemy import SAProvider

__all__ = ["PROVIDER_ATTRIBUTE", "run_migrations", "write_migrations_folder"]

# The key in Alembic's ``Config.attributes`` under which a Protean command
# passes the provider to ``run_migrations``.
PROVIDER_ATTRIBUTE = "protean_provider"

# Set while ``run_migrations`` runs, so a nested call returns at once.
_running = False


def _template(name: str) -> str:
    return resources.files(__name__).joinpath("templates", name).read_text("utf-8")


def write_migrations_folder(
    directory: Path, domain_path: str, provider_name: str
) -> None:
    """Write an empty migrations folder for one provider into ``directory``.

    The folder holds ``alembic.ini``, which records ``domain_path`` and
    ``provider_name``, ``env.py``, ``script.py.mako`` and an empty ``versions/``.
    ``directory`` and its parents are created when missing.

    Raises:
        ConfigurationError: ``directory`` exists and is not an empty folder.
            Nothing is written.
    """
    if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
        raise ConfigurationError(
            f"Cannot create migrations in '{directory}': it already exists and "
            "is not empty. Choose another folder with --directory."
        )

    # configparser reads ``%`` as the start of an interpolation, so a literal
    # ``%`` in a recorded value is written as ``%%``.
    ini = string.Template(_template("alembic.ini.tmpl")).substitute(
        domain=domain_path.replace("%", "%%"),
        provider=provider_name.replace("%", "%%"),
    )

    (directory / "versions").mkdir(parents=True)
    (directory / "alembic.ini").write_text(ini, encoding="utf-8")
    (directory / "env.py").write_text(_template("env.py.tmpl"), encoding="utf-8")
    (directory / "script.py.mako").write_text(
        _template("script.py.mako"), encoding="utf-8"
    )


def run_migrations() -> None:
    """Run Alembic's migration environment for one Protean provider.

    Every ``env.py`` that ``write_migrations_folder`` writes calls this. A
    Protean command passes the provider in ``Config.attributes`` under
    ``PROVIDER_ATTRIBUTE``. A plain ``alembic`` run passes none, so the
    domain is loaded from the ``protean_domain`` option of ``alembic.ini`` and
    the provider is the one ``protean_provider`` names.

    Migrations run on the provider's engine, or, in offline mode, render SQL
    for the provider's database URL. The target metadata is the provider's
    ``metadata``.

    Does nothing when no Alembic command is running, and when called again
    while a run is in progress.

    Raises:
        ConfigurationError: ``alembic.ini`` names no domain, a domain that
            cannot be loaded, or a provider the domain does not configure.
    """
    # Domain traversal imports every module beside the domain file and in its
    # immediate subfolders, so a ``migrations/`` folder next to ``domain.py``
    # has its ``env.py`` imported while the domain loads. That happens outside
    # any Alembic run when a Protean command loads the domain, and inside a
    # run of another provider's folder (``migrations/analytics/``) when this
    # function loads it. Neither import may start a run.
    global _running
    if _running:
        return
    try:
        from alembic import context  # noqa: PLC0415
    except ImportError:
        return
    # Alembic sets ``context.config`` only while it runs ``env.py``.
    config = getattr(context, "config", None)
    if config is None:
        return

    _running = True
    try:
        _run(context, _provider_for(config))
    finally:
        _running = False


def _provider_for(config: Any) -> SAProvider:
    """The provider a Protean command passed, or the one ``alembic.ini`` names."""
    provider: SAProvider | None = config.attributes.get(PROVIDER_ATTRIBUTE)
    if provider is not None:
        return provider

    # A plain ``alembic`` run sets up its own logging from ``alembic.ini``.
    if config.config_file_name is not None and config.file_config.has_section(
        "loggers"
    ):
        fileConfig(config.config_file_name, disable_existing_loggers=False)

    domain_path = config.get_main_option("protean_domain")
    if not domain_path:
        raise ConfigurationError(
            f"'{config.config_file_name}' has no 'protean_domain' option in its "
            "[alembic] section, so the domain cannot be loaded."
        )
    domain = derive_domain(domain_path)
    if domain is None:
        raise ConfigurationError(f"No Protean domain found at '{domain_path}'.")
    domain.init()

    provider_name = config.get_main_option("protean_provider") or "default"
    if provider_name not in domain.providers:
        raise ConfigurationError(
            f"Provider '{provider_name}' named in '{config.config_file_name}' is "
            f"not configured. Configured providers: "
            f"{', '.join(sorted(domain.providers))}."
        )
    return cast("SAProvider", domain.providers[provider_name])


def _run(context: Any, provider: SAProvider) -> None:
    with provider.domain.domain_context():
        metadata = provider.metadata
        if context.is_offline_mode():
            context.configure(
                url=provider._engine.url,
                target_metadata=metadata,
                literal_binds=True,
                dialect_opts={"paramstyle": "named"},
            )
            with context.begin_transaction():
                context.run_migrations()
            return

        with provider._engine.connect() as connection:
            context.configure(connection=connection, target_metadata=metadata)
            with context.begin_transaction():
                context.run_migrations()
