""" Package for  Concrete Implementations of Protean repositories """
# Standard Library Imports
import importlib
import logging

# Protean
from protean.core.exceptions import ConfigurationError
from protean.utils import DomainObjects, fully_qualified_name

logger = logging.getLogger("protean.repository")


class Providers:
    def __init__(self, domain):
        self.domain = domain
        self._providers = None

    def get_model(self, aggregate_cls):
        """Retrieve Model class connected to Entity"""
        # Return model if already constructed
        if fully_qualified_name(aggregate_cls) in self.domain._constructed_models:
            return self.domain._constructed_models[fully_qualified_name(aggregate_cls)]

        # Fixate on the provider associated with the aggregate class
        aggregate_record = self.domain._get_element_by_class(
            (DomainObjects.AGGREGATE, DomainObjects.ENTITY), aggregate_cls
        )
        provider = self.get_provider(aggregate_record.cls.meta_.provider)

        # If a model was associated with the aggregate record, give it a higher priority
        #   and do not bake a new model class from aggregate/entity attributes
        custom_model_cls = None
        if fully_qualified_name(aggregate_cls) in self.domain._models:
            custom_model_cls = self.domain._models[fully_qualified_name(aggregate_cls)]

        if custom_model_cls:
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
                provider_objects[provider_name] = provider_cls(
                    provider_name, self, conn_info
                )

        return provider_objects

    def has_provider(self, provider_name):
        if self._providers is None:
            self._providers = self._initialize_providers()

        return provider_name in self._providers

    def get_provider(self, provider_name):
        """Retrieve the provider object with a given provider name"""
        if self._providers is None:
            self._providers = self._initialize_providers()

        try:
            return self._providers[provider_name]
        except KeyError:
            raise AssertionError(f"No Provider registered with name {provider_name}")

    def get_connection(self, provider_name="default"):
        """Fetch connection from Provider"""
        if self._providers is None:
            self._providers = self._initialize_providers()

        try:
            return self._providers[provider_name].get_connection()
        except KeyError:
            raise AssertionError(f"No Provider registered with name {provider_name}")

    def providers_list(self):
        """A generator that helps users iterator through providers"""
        if self._providers is None:
            self._providers = self._initialize_providers()

        for provider_name in self._providers:
            yield self._providers[provider_name]

    def repository_for(self, aggregate_cls):
        """Retrieve a Repository registered for the Aggregate"""
        # Protean
        from protean.core.aggregate import BaseAggregate

        if not issubclass(aggregate_cls, BaseAggregate):
            raise AssertionError(
                f"Element {aggregate_cls.__name__} must be subclass of `BaseAggregate`"
            )

        try:
            repository_record = next(
                repository
                for _, repository in self.domain.registry.repositories.items()
                if repository.cls.meta_.aggregate_cls.__name__ == aggregate_cls.__name__
            )
        except StopIteration:
            logger.debug(f"Constructing a Repository for {aggregate_cls}...")

            # Protean
            from protean.core.repository import BaseRepository

            new_class = type(
                aggregate_cls.__name__ + "Repository", (BaseRepository,), {}
            )

            self.domain._domain_element(
                DomainObjects.REPOSITORY, _cls=new_class, aggregate_cls=aggregate_cls,
            )

            # FIXME Avoid comparing classes / Fetch a Repository class directly by its aggregate class
            repository_record = next(
                repository
                for _, repository in self.domain.registry.repositories.items()
                if repository.cls.meta_.aggregate_cls.__name__ == aggregate_cls.__name__
            )

        return repository_record.cls()

    def get_dao(self, aggregate_cls):
        """Retrieve a DAO registered for the Aggregate with a live connection"""
        # Fixate on the provider associated with the aggregate class
        aggregate_record = self.domain._get_element_by_class(
            (DomainObjects.AGGREGATE, DomainObjects.ENTITY), aggregate_cls
        )
        provider = self.get_provider(aggregate_record.cls.meta_.provider)

        # Fixate on Model class at the domain level because an explicit model may have been registered
        model_cls = self.get_model(aggregate_record.cls)

        return provider.get_dao(aggregate_record.cls, model_cls)
