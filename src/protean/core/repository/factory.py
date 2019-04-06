""" Factory class for managing repository connections"""
import logging
from collections import namedtuple
from threading import local

from protean.core.exceptions import ConfigurationError
from protean.core.provider import providers
from protean.utils.generic import fully_qualified_name

logger = logging.getLogger('protean.repository')


class RepositoryFactory:
    """Repository Factory interface to retrieve Resource Objects from Repositories

    FIXME RepositoryFactory should prepare adapter objects JIT, so that connections
        are kept open only for the necessary duration. Once the request is handled, it should
        be let go.
    """

    # EntityRecord Inner Class, implemented as a namedtuple for ease of use.
    #   This class will store attributes related to Entity and Models, and will be objects
    #   in the registry dictionary.
    EntityRecord = namedtuple(
        'EntityRecord',
        'name, qualname, entity_cls, provider_name, model_cls, fully_baked_model')

    def __init__(self):
        """"Initialize repository factory"""
        self._registry = {}
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
        entity_name = fully_qualified_name(model_cls.opts_.entity_cls)
        provider_name = provider_name or model_cls.opts_.bind or 'default'

        try:
            entity = self._get_entity_by_class(model_cls.opts_.entity_cls)

            if entity:
                # This probably is an accidental re-registration of the entity
                #   and we should warn the user of a possible repository confusion
                raise ConfigurationError(
                    f'Entity {entity_name} has already been registered')
        except AssertionError:
            # Entity has not been registered yet. Let's go ahead and add it to the registry.
            entity_record = RepositoryFactory.EntityRecord(
                name=model_cls.opts_.entity_cls.__name__,
                qualname=entity_name,
                entity_cls=model_cls.opts_.entity_cls,
                provider_name=provider_name,
                model_cls=model_cls,
                fully_baked_model=False
            )
            self._registry[entity_name] = entity_record
            logger.debug(
                f'Registered model {model_name} for entity {entity_name} with provider'
                f' {provider_name}.')

    def _find_entity_in_records_by_class_name(self, entity_name):
        """Fetch by Entity Name in values"""
        records = {
            key: value for (key, value)
            in self._registry.items()
            if value.name == entity_name
        }
        # If more than one record was found, we are dealing with the case of
        #   an Entity name present in multiple places (packages or plugins). Throw an error
        #   and ask for a fully qualified Entity name to be specified
        if len(records) > 1:
            raise ConfigurationError(
                f'Entity with name {entity_name} has been registered twice. '
                f'Please use fully qualified Entity name to specify the exact Entity.')
        elif len(records) == 1:
            return next(iter(records.values()))
        else:
            raise AssertionError(f'No Entity registered with name {entity_name}')

    def _get_entity_by_class(self, entity_cls):
        """Fetch Entity record with Entity class details"""
        entity_qualname = fully_qualified_name(entity_cls)
        if entity_qualname in self._registry:
            return self._registry[entity_qualname]
        else:
            return self._find_entity_in_records_by_class_name(entity_cls.__name__)

    def _get_entity_by_name(self, entity_name):
        """Fetch Entity record with an Entity name"""
        if entity_name in self._registry:
            return self._registry[entity_name]
        else:
            return self._find_entity_in_records_by_class_name(entity_name)

    def _validate_model_cls(self, model_cls):
        """Validate that Model is a valid class"""
        # Import here to avoid cyclic dependency
        from .model import BaseModel

        if not issubclass(model_cls, BaseModel):
            raise AssertionError(
                f'Model {model_cls} must be subclass of `BaseModel`')

    def get_model(self, entity_cls):
        """Retrieve Model class connected to Entity"""
        entity_record = self._get_entity_by_class(entity_cls)

        model_cls = None
        if entity_record.fully_baked_model:
            model_cls = entity_record.model_cls
        else:
            provider = self.get_provider(entity_record.provider_name)
            baked_model_cls = provider.get_model(entity_record.model_cls)

            # Record for future reference
            new_entity_record = entity_record._replace(model_cls=baked_model_cls,
                                                       fully_baked_model=True)
            self._registry[entity_record.qualname] = new_entity_record

            model_cls = baked_model_cls

        return model_cls

    def get_entity(self, entity_name):
        """Retrieve Entity class registered by `entity_name`"""
        return self._get_entity_by_name(entity_name).entity_cls

    def get_provider(self, provider_name):
        """Retrieve the provider object with a given provider name"""
        return providers.get_provider(provider_name)

    def get_repository(self, entity_cls):
        """Retrieve a Repository for the Model with a live connection"""
        entity_record = self._get_entity_by_class(entity_cls)
        provider = self.get_provider(entity_record.provider_name)

        return provider.get_repository(entity_record.model_cls)


repo_factory = RepositoryFactory()
