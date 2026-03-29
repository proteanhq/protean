"""Package for Concrete Implementations of Protean repositories"""

import collections
import logging
from collections import defaultdict

from protean.core.repository import BaseRepository, repository_factory
from protean.exceptions import ConfigurationError
from protean.port.provider import registry
from protean.utils import fully_qualified_name

logger = logging.getLogger(__name__)


class Providers(collections.abc.MutableMapping):
    def __init__(self, domain):
        self.domain = domain
        self._providers = None

        # Recognized Repositories are memoized within providers
        # for subsequent calls.
        #
        # Structure:
        # {
        #    'app.User': {
        #        'ALL': UserRepository,
        #        'sqlite': UserSQLiteRepository,
        #        'postgresql': UserPostgresRepository,
        #    }
        # }
        self._repositories: dict[str, dict[str, type]] = defaultdict(dict)

    def __getitem__(self, key):
        return self._providers[key] if self._providers else None

    def __iter__(self):
        return iter(self._providers) if self._providers else iter({})

    def __len__(self):
        return len(self._providers) if self._providers else 0

    def __setitem__(self, key, value):
        if self._providers is None:
            self._providers = {}

        self._providers[key] = value

    def __delitem__(self, key):
        assert self._providers is not None
        if key in self._providers:
            del self._providers[key]

    def _construct_repository(self, part_of):
        repository_cls = type(part_of.__name__ + "Repository", (BaseRepository,), {})
        repository_cls = repository_factory(
            repository_cls, self.domain, part_of=part_of, _auto_constructed=True
        )
        return repository_cls

    def _register_repository(self, part_of, repository_cls):
        # When explicitly provided, the value of `database` will be the actual database in use
        # and will lock the repository to that type of database.
        # For example, with the following PostgreSQL configuration:
        #   databases = {
        #       "default": {
        #           "provider": "postgresql",
        #           "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
        #       },
        #   }
        #
        # And repository as:
        #   @domain.repository(part_of=Post, database="postgresql")
        #   class CustomPostRepository:
        #       def custom_method(self):
        #           ...
        #
        # The value of `database` would be `postgresql`.
        #
        # In the absence of an explicit database value, the repository is associated with "ALL"
        # and is used for all databases.
        database = repository_cls.meta_.database

        aggregate_name = fully_qualified_name(part_of)

        self._repositories[aggregate_name][database] = repository_cls

    def _initialize(self):
        """Read config file and initialize providers"""
        # Close existing providers to prevent connection leaks when
        # re-initializing (e.g., when domain.init() is called after
        # the initial domain._initialize())
        if self._providers:
            for provider in self._providers.values():
                provider.close()

        configured_providers = self.domain.config["databases"]
        provider_objects = {}

        if configured_providers and isinstance(configured_providers, dict):
            if "default" not in configured_providers:
                raise ConfigurationError("You must define a 'default' provider")

            for provider_name, conn_info in configured_providers.items():
                provider_type = conn_info.get("provider")
                provider_cls = registry.get(provider_type)
                provider = provider_cls(provider_name, self.domain, conn_info)

                # Initialize a connection to check if everything is ok
                conn = provider.is_alive()
                if not conn:
                    raise ConfigurationError(
                        f"Could not connect to database at {conn_info['database_uri']}"
                    )

                provider_objects[provider_name] = provider

        self._providers = provider_objects

    def get_connection(self, provider_name="default"):
        """Fetch connection from Provider"""
        if self._providers is None:
            self._initialize()

        assert self._providers is not None

        if provider_name not in self._providers:
            configured = sorted(self._providers.keys()) if self._providers else []
            raise ConfigurationError(
                f"No provider configured with name '{provider_name}'. "
                f"Configured providers: {', '.join(configured) or 'none'}"
            )
        return self._providers[provider_name].get_connection()

    def repository_for(self, part_of) -> BaseRepository:
        """Retrieve a Repository registered for the Aggregate"""
        if self._providers is None:
            self._initialize()

        provider_name = part_of.meta_.provider
        assert self._providers is not None

        if provider_name not in self._providers:
            configured = sorted(self._providers.keys()) if self._providers else []
            raise ConfigurationError(
                f"No provider configured with name '{provider_name}'. "
                f"Configured providers: {', '.join(configured) or 'none'}"
            )
        provider = self._providers[provider_name]
        database = provider.__class__.__database__

        aggregate_name = fully_qualified_name(part_of)

        # One-time repository registration process for Aggregates
        #
        # We first cycle through repositories registered with the domain
        # and cache them within providers. We also construct a generic
        # repository dynamically that would work with the other providers.
        if aggregate_name not in self._repositories:
            # First, register all explicitly-defined repositories
            for _, repository in self.domain.registry.repositories.items():
                if repository.cls.meta_.part_of.__name__ == part_of.__name__:
                    self._register_repository(part_of, repository.cls)

            # Next, check if a generic repository has been registered, otherwise construct
            if "ALL" not in self._repositories[aggregate_name]:
                self._register_repository(part_of, self._construct_repository(part_of))

        # If the aggregate is tied to a database, return the database-specific repository
        if database in self._repositories[aggregate_name]:
            repository_cls = self._repositories[aggregate_name][database]
        # Else return the generic repository
        else:
            repository_cls = self._repositories[aggregate_name]["ALL"]

        return repository_cls(self.domain, provider)
