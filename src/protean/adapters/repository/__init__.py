""" Package for  Concrete Implementations of Protean repositories """
import collections
import importlib
import logging

from collections import defaultdict

from protean.core.repository import BaseRepository, repository_factory
from protean.exceptions import ConfigurationError
from protean.utils import fully_qualified_name

logger = logging.getLogger(__name__)


class Providers(collections.abc.MutableMapping):
    def __init__(self, domain):
        self.domain = domain

        # Providers will be filled dynamically on first call to
        # fetch a repository. This is designed so that the entire
        # domain is loaded before we try to load providers.
        # FIXME Should this be done during domain.init()
        self._providers = None

        # Recognized Repositories are memoized within providers
        # for subsequent calls.
        #
        # Structure:
        # {
        #    'app.User': {
        #        'ALL': UserRepository,
        #        'SQLITE': UserSQLiteRepository,
        #        'POSTGRESQL': UserPostgresRepository,
        #    }
        # }
        self._repositories = defaultdict(lambda: defaultdict(str))

    def __getitem__(self, key):
        if self._providers is None:
            self._initialize()
        return self._providers[key]

    def __iter__(self):
        if self._providers is None:
            self._initialize()
        return iter(self._providers)

    def __len__(self):
        if self._providers is None:
            self._initialize()
        return len(self._providers)

    def __setitem__(self, key, value):
        if self._providers is None:
            self._initialize()
        self._providers[key] = value

    def __delitem__(self, key):
        if self._providers is None:
            self._initialize()
        del self._providers[key]

    def _construct_repository(self, aggregate_cls):
        repository_cls = type(
            aggregate_cls.__name__ + "Repository", (BaseRepository,), {}
        )
        repository_cls = repository_factory(repository_cls, aggregate_cls=aggregate_cls)
        return repository_cls

    def _register_repository(self, aggregate_cls, repository_cls):
        # When explicitly provided, the value of `database` will be the actual database in use
        # and will lock the repository to that type of database.
        # For example, with the following PostgreSQL configuration:
        #   DATABASES = {
        #       "default": {
        #           "PROVIDER": "protean.adapters.repository.sqlalchemy.SAProvider",
        #           "DATABASE": Database.POSTGRESQL.value,
        #           "DATABASE_URI": "postgresql://postgres:postgres@localhost:5432/postgres",
        #       },
        #   }
        #
        # And repository as:
        #   class CustomPostRepository:
        #       class Meta:
        #           database = Database.POSTGRESQL.value
        # The value of `database` would be `POSTGRESQL`.
        #
        # In the absence of an explicit database value, the repository is associated with "ALL"
        # and is used for all databases.
        database = repository_cls.meta_.database

        aggregate_name = fully_qualified_name(aggregate_cls)

        self._repositories[aggregate_name][database] = repository_cls

    def _initialize(self):
        """Read config file and initialize providers"""
        configured_providers = self.domain.config["DATABASES"]
        provider_objects = {}

        if configured_providers and isinstance(configured_providers, dict):
            if "default" not in configured_providers:
                raise ConfigurationError("You must define a 'default' provider")

            for provider_name, conn_info in configured_providers.items():
                provider_full_path = conn_info["PROVIDER"]
                provider_module, provider_class = provider_full_path.rsplit(
                    ".", maxsplit=1
                )

                provider_cls = getattr(
                    importlib.import_module(provider_module), provider_class
                )
                provider = provider_cls(provider_name, self.domain, conn_info)

                provider_objects[provider_name] = provider

        self._providers = provider_objects

    def get_connection(self, provider_name="default"):
        """Fetch connection from Provider"""
        if self._providers is None:
            self._initialize()

        try:
            return self._providers[provider_name].get_connection()
        except KeyError:
            raise AssertionError(f"No Provider registered with name {provider_name}")

    def repository_for(self, aggregate_cls):
        """Retrieve a Repository registered for the Aggregate"""
        if self._providers is None:
            self._initialize()

        provider_name = aggregate_cls.meta_.provider
        provider = self._providers[provider_name]
        database = provider.conn_info["DATABASE"]

        aggregate_name = fully_qualified_name(aggregate_cls)

        # One-time repository registration process for Aggregates
        #
        # We first cycle through repositories registered with the domain
        # and cache them within providers. We also construct a generic
        # repository dynamically that would work with the other providers.
        # FIXME Should we construct generic repositories?
        # FIXME Will this run multiple times?
        if aggregate_name not in self._repositories:
            # First, register all explicitly-defined repositories
            for _, repository in self.domain.registry.repositories.items():
                if (
                    repository.cls.meta_.aggregate_cls.__name__
                    == aggregate_cls.__name__
                ):
                    self._register_repository(aggregate_cls, repository.cls)

            # Next, check if a generic repository has been registered, otherwise construct
            if "ALL" not in self._repositories[aggregate_name]:
                self._register_repository(
                    aggregate_cls, self._construct_repository(aggregate_cls)
                )

        # If the aggregate is tied to a database, return the database-specific repository
        if database in self._repositories[aggregate_name]:
            repository_cls = self._repositories[aggregate_name][database]
        # Else return the generic repository
        else:
            repository_cls = self._repositories[aggregate_name]["ALL"]

        return repository_cls(self.domain, provider)
