"""Infrastructure lifecycle management extracted from the Domain class.

The ``InfrastructureManager`` owns outbox initialization, database setup,
truncation, and drop operations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from inflection import camelize

from protean.exceptions import ConfigurationError
from protean.utils import clone_class
from protean.utils.consume_idempotency import (
    PROCESSED_MESSAGE_INDEXES,
    ProcessedMessage,
    ProcessedMessageRepository,
)
from protean.utils.outbox import OUTBOX_INDEXES, Outbox, OutboxRepository

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class InfrastructureManager:
    """Manage database and outbox lifecycle operations.

    Instantiated once by ``Domain.__init__()`` and called during
    ``Domain.init()`` and by public lifecycle methods.
    """

    def __init__(self, domain: Domain) -> None:
        self._domain = domain
        self.outbox_repos: dict = {}
        self.processed_message_repos: dict = {}

    def _initialize_per_provider(
        self,
        base_cls: type,
        repo_cls: type,
        schema_name: str,
        indexes: list,
        target: dict,
        label: str,
    ) -> None:
        """Synthesize a per-provider aggregate + repository for a framework table.

        Shared by the outbox and the consume-side idempotency marker: both
        clone a base aggregate/repository per managed provider, register them,
        and store the repository in ``target`` keyed by provider name.
        """
        domain = self._domain

        if not (
            hasattr(domain.providers, "_providers")
            and domain.providers._providers is not None
        ):
            logger.debug(
                "No providers configured during domain initialization. "
                "%s repositories will be created lazily.",
                label,
            )
            return

        for provider_name, provider in domain.providers._providers.items():
            if not provider.managed:
                continue
            try:
                new_cls = clone_class(
                    base_cls, f"{camelize(provider_name)}{base_cls.__name__}"
                )
                domain.register(
                    new_cls,
                    internal=True,
                    auto_generated=True,
                    schema_name=schema_name,
                    provider=provider_name,
                    indexes=indexes,
                )

                new_repo_cls = clone_class(
                    repo_cls, f"{camelize(provider_name)}{repo_cls.__name__}"
                )
                domain.register(
                    new_repo_cls,
                    internal=True,
                    auto_generated=True,
                    part_of=new_cls,
                )
                domain.providers._register_repository(new_cls, new_repo_cls)

                target[provider_name] = domain.repository_for(new_cls)
            except Exception as e:
                raise ConfigurationError(
                    f"Failed to initialize {label} for provider "
                    f"'{provider_name}': {str(e)}"
                )

    def initialize_outbox(self) -> None:
        """Initialize outbox repositories for all managed providers."""
        self._initialize_per_provider(
            Outbox,
            OutboxRepository,
            "outbox",
            OUTBOX_INDEXES,
            self.outbox_repos,
            "outbox",
        )

    def get_outbox_repo(self, provider_name: str):
        """Get outbox repository for a specific provider."""
        if not self.outbox_repos:
            self.initialize_outbox()

        return self.outbox_repos[provider_name]

    def initialize_processed_messages(self) -> None:
        """Initialize a consume-side idempotency marker per managed provider.

        Synthesizes a per-provider ``ProcessedMessage`` aggregate + repository
        so an ``idempotent=True`` projector can record a ``(message_id,
        handler)`` marker in the same transaction as its read-model write.
        See ADR-0017.
        """
        self._initialize_per_provider(
            ProcessedMessage,
            ProcessedMessageRepository,
            "processed_message",
            PROCESSED_MESSAGE_INDEXES,
            self.processed_message_repos,
            "consume-side idempotency",
        )

    def get_processed_message_repo(self, provider_name: str):
        """Get the consume-side idempotency repository for a provider."""
        if not self.processed_message_repos:
            self.initialize_processed_messages()

        return self.processed_message_repos[provider_name]

    def setup_database(self) -> None:
        """Create all database tables (aggregates, entities, projections, outbox,
        and the consume-side idempotency marker).

        Delegates to each managed provider's ``_create_database_artifacts()``
        which is idempotent — existing tables are left untouched.
        Providers with ``managed = false`` are skipped.

        Forces the outbox and idempotency-marker DAOs first so their table
        definitions are registered in SQLAlchemy metadata before ``create_all()``
        runs.
        """
        # Force DAO creation for outbox repos so their tables are included
        for _provider_name, outbox_repo in self.outbox_repos.items():
            outbox_repo._dao  # noqa: B018

        # Same for the consume-side idempotency marker tables.
        for _provider_name, pm_repo in self.processed_message_repos.items():
            pm_repo._dao  # noqa: B018

        for _, provider in self._domain.providers.items():
            if not provider.managed:
                continue
            provider._create_database_artifacts()

    def setup_outbox(self) -> None:
        """Create only outbox tables.

        Useful when migrating from event-store to stream subscriptions where
        aggregate tables already exist.

        Raises ``ConfigurationError`` if the outbox is not enabled.
        """
        if not self._domain.has_outbox:
            raise ConfigurationError(
                "Outbox is not enabled. Set "
                "'server.default_subscription_type = \"stream\"' "
                "in your domain configuration."
            )
        # Force DAO creation for outbox repos, then create pending tables
        for _provider_name, outbox_repo in self.outbox_repos.items():
            outbox_repo._dao  # noqa: B018
        for _, provider in self._domain.providers.items():
            if not provider.managed:
                continue
            provider._create_database_artifacts()  # Idempotent

    def truncate_database(self) -> None:
        """Delete all rows from every table without dropping the tables.

        Clears aggregate/projection tables in all managed providers and the
        event store messages table. Providers with ``managed = false`` are
        skipped.
        """
        domain = self._domain

        # Ensure provider metadata is populated (idempotent)
        self.setup_database()

        for _, provider in domain.providers.items():
            if not provider.managed:
                continue
            provider._data_reset()

        domain.event_store.store._data_reset()

    def drop_database(self) -> None:
        """Drop all database tables for managed providers.

        Providers with ``managed = false`` are skipped.
        """
        for _, provider in self._domain.providers.items():
            if not provider.managed:
                continue
            provider._drop_database_artifacts()
