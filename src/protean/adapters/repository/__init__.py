""" Package for  Concrete Implementations of Protean repositories """
import importlib
import logging

from collections import defaultdict

from protean.core.repository import BaseRepository, repository_factory
from protean.exceptions import ConfigurationError
from protean.utils import DomainObjects, fully_qualified_name

logger = logging.getLogger("protean.repository")


class Providers:
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

    def get_model(self, aggregate_cls):
        """Retrieve Model class connected to Entity"""
        # Return model if already constructed
        if fully_qualified_name(aggregate_cls) in self.domain._constructed_models:
            return self.domain._constructed_models[fully_qualified_name(aggregate_cls)]

        # Fixate on the provider associated with the aggregate class
        aggregate_record = self.domain._get_element_by_class(
            (DomainObjects.AGGREGATE, DomainObjects.ENTITY, DomainObjects.VIEW),
            aggregate_cls,
        )
        provider = self.get_provider(aggregate_record.cls.meta_.provider)

        # If a model was associated with the aggregate record, give it a higher priority
        #   and do not bake a new model class from aggregate/entity attributes
        custom_model_cls = None
        if fully_qualified_name(aggregate_cls) in self.domain._models:
            custom_model_cls = self.domain._models[fully_qualified_name(aggregate_cls)]

        # FIXME This is the provide support for activating database specific models
        #   This needs to be enhanced to allow Protean to hold multiple models per Aggregate/Entity
        #   per database.
        #
        #   If no database is specified, model can be used for all databases
        if custom_model_cls and (
            custom_model_cls.meta_.database is None
            or custom_model_cls.meta_.database == provider.conn_info["DATABASE"]
        ):
            # Get the decorated model class.
            #   This is a no-op if the provider decides that the model is fully-baked
            model_cls = provider.decorate_model_class(
                aggregate_record.cls, custom_model_cls
            )
        else:
            # No model was associated with the aggregate/entity explicitly.
            #   So ask the Provider to bake a new model, initialized properly for this aggregate
            #   and return it
            model_cls = provider.construct_model_class(aggregate_record.cls)

        self.domain._constructed_models[fully_qualified_name(aggregate_cls)] = model_cls
        return model_cls

    def _initialize_providers(self):
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
                provider = provider_cls(provider_name, self, conn_info)

                provider_objects[provider_name] = provider

        self._providers = provider_objects

    def has_provider(self, provider_name):
        if self._providers is None:
            self._initialize_providers()

        return provider_name in self._providers

    def get_provider(self, provider_name):
        """Retrieve the provider object with a given provider name"""
        if self._providers is None:
            self._initialize_providers()

        try:
            return self._providers[provider_name]
        except KeyError:
            raise AssertionError(f"No Provider registered with name {provider_name}")

    def get_connection(self, provider_name="default"):
        """Fetch connection from Provider"""
        if self._providers is None:
            self._initialize_providers()

        try:
            return self._providers[provider_name].get_connection()
        except KeyError:
            raise AssertionError(f"No Provider registered with name {provider_name}")

    def providers_list(self):
        """A generator that helps users iterator through providers"""
        if self._providers is None:
            self._initialize_providers()

        for provider_name in self._providers:
            yield self._providers[provider_name]

    def repository_for(self, aggregate_cls):
        """Retrieve a Repository registered for the Aggregate"""
        if self._providers is None:
            self._initialize_providers()

        provider = aggregate_cls.meta_.provider
        database = self.get_provider(provider).conn_info["DATABASE"]

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

        return repository_cls()

    def get_dao(self, aggregate_cls):
        """Retrieve a DAO registered for the Aggregate with a live connection"""
        # Fixate on the provider associated with the aggregate class
        aggregate_record = self.domain._get_element_by_class(
            (DomainObjects.AGGREGATE, DomainObjects.ENTITY, DomainObjects.VIEW),
            aggregate_cls,
        )
        provider = self.get_provider(aggregate_record.cls.meta_.provider)

        # Fixate on Model class at the domain level because an explicit model may have been registered
        model_cls = self.get_model(aggregate_record.cls)

        return provider.get_dao(aggregate_record.cls, model_cls)
