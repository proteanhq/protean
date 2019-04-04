""" Factory class for managing repository connections"""
import logging
from threading import local

from protean.core.exceptions import ConfigurationError
from protean.core.provider import providers

logger = logging.getLogger('protean.repository')


class RepositoryFactory:
    """Repository Factory interface to retrieve Resource Objects from Repositories

    FIXME RepositoryFactory should prepare adapter objects JIT, so that connections
        are kept open only for the necessary duration. Once the request is handled, it should
        be let go.
    """

    def __init__(self):
        """"Initialize repository factory"""
        self._provider_registry = {}
        self._entity_registry = {}
        self._model_registry = {}
        self._fully_baked_models = {}
        self._connections = local()

    def register(self, model_cls, provider_name=None):
        """ Register the given model with the factory
        :param model_cls: class of the model to be registered
        :param adapter_cls: Optional adapter class to use if not the
        `Adapter` defined by the provider is user
        """
        self._validate_model_cls(model_cls)

        # Register the model if it does not exist
        model_name = model_cls.__name__
        entity_name = model_cls.opts_.entity_cls.__name__

        if self._provider_registry.get(entity_name):
            # This probably is an accidental re-registration of the entity
            #   and we should warn the user of a possible repository confusion
            raise ConfigurationError(
                f'Entity {entity_name} has already been registered')
        else:
            self._provider_registry[entity_name] = provider_name or model_cls.opts_.bind or 'default'
            self._model_registry[entity_name] = model_cls
            self._entity_registry[entity_name] = model_cls.opts_.entity_cls
            logger.debug(
                f'Registered model {model_name} for entity {entity_name} with provider'
                f' {provider_name}.')

    def _validate_model_cls(self, model_cls):
        """Validate that Model is a valid class"""
        # Import here to avoid cyclic dependency
        from .model import BaseModel

        if not issubclass(model_cls, BaseModel):
            raise AssertionError(
                f'Model {model_cls} must be subclass of `BaseModel`')

    def get_model(self, entity_name):
        """Retrieve Model class connected to Entity"""
        if entity_name in self._fully_baked_models:
            return self._fully_baked_models[entity_name]

        try:
            # This will trigger ``AssertionError`` if entity is not registered
            model_cls = self._model_registry[entity_name]

            provider = self.get_provider(entity_name)
            fully_baked_model = provider.get_model(model_cls)

            # Record for future reference
            self._fully_baked_models['entity_name'] = fully_baked_model

            return fully_baked_model
        except KeyError:
            raise AssertionError(f'No Model registered for {entity_name}')

    def get_entity(self, entity_name):
        """Retrieve Entity class registered by `entity_name`"""
        try:
            return self._entity_registry[entity_name]
        except KeyError:
            raise AssertionError(f'No Entity registered with name {entity_name}')

    def get_provider(self, entity_name):
        """Retrieve the provider name registered for the entity"""
        provider_name = self._provider_registry[entity_name]
        return providers.get_provider(provider_name)

    def __getattr__(self, entity_name):
        try:
            provider = self.get_provider(entity_name)

            # Fetch a repository object with live connection
            return provider.get_repository(self._model_registry[entity_name])
        except KeyError:
            raise AssertionError(f'No Model registered for {entity_name}')


repo_factory = RepositoryFactory()
