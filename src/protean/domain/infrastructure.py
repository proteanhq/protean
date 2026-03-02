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
from protean.utils.outbox import Outbox, OutboxRepository

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

    def initialize_outbox(self) -> None:
        """Initialize outbox repositories for all configured providers.

        Constructs and stores outbox repositories for each provider,
        verifying that the outbox table exists in the database.
        """
        domain = self._domain

        if (
            hasattr(domain.providers, "_providers")
            and domain.providers._providers is not None
        ):
            for provider_name in domain.providers._providers.keys():
                try:
                    # Synthesize new outbox class specific to this provider
                    new_name = f"{camelize(provider_name)}Outbox"
                    new_cls = clone_class(Outbox, new_name)

                    domain.register(
                        new_cls,
                        internal=True,
                        auto_generated=True,
                        schema_name="outbox",
                        provider=provider_name,
                    )

                    # Synthesize new repository class specific to this provider
                    new_repo_name = f"{camelize(provider_name)}OutboxRepository"
                    new_repo_cls = clone_class(OutboxRepository, new_repo_name)

                    domain.register(
                        new_repo_cls,
                        internal=True,
                        auto_generated=True,
                        part_of=new_cls,
                    )
                    domain.providers._register_repository(new_cls, new_repo_cls)

                    outbox_repo = domain.repository_for(new_cls)
                    self.outbox_repos[provider_name] = outbox_repo

                except Exception as e:
                    raise ConfigurationError(
                        f"Failed to initialize outbox for provider '{provider_name}': {str(e)}"
                    )
        else:
            logger.debug(
                "No providers configured during domain initialization. "
                "Outbox repositories will be created lazily."
            )

    def get_outbox_repo(self, provider_name: str):
        """Get outbox repository for a specific provider."""
        if not self.outbox_repos:
            self.initialize_outbox()

        return self.outbox_repos[provider_name]

    def setup_database(self) -> None:
        """Create all database tables (aggregates, entities, projections, outbox).

        Delegates to each provider's ``_create_database_artifacts()`` which is
        idempotent — existing tables are left untouched.
        """
        for _, provider in self._domain.providers.items():
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
            provider._create_database_artifacts()  # Idempotent

    def truncate_database(self) -> None:
        """Delete all rows from every table without dropping the tables.

        Clears aggregate/projection tables in all providers and the event
        store messages table.
        """
        domain = self._domain

        # Ensure provider metadata is populated (idempotent)
        self.setup_database()

        for _, provider in domain.providers.items():
            provider._data_reset()

        domain.event_store.store._data_reset()

    def drop_database(self) -> None:
        """Drop all database tables."""
        for _, provider in self._domain.providers.items():
            provider._drop_database_artifacts()
