""" Factory class for managing repository connections"""
import logging
from collections import namedtuple
from threading import local

from protean.core.exceptions import ConfigurationError
from protean.core.exceptions import NotSupportedError
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
        'name, qualname, entity_cls, provider_name, model_cls')

    def __init__(self):
        """"Initialize repository factory"""
        self._registry = {}
        self._connections = local()

    def register(self, entity_cls, provider_name=None):
        """ Register the given model with the factory
        :param entity_cls: Entity class to be registered
        :param provider: Optional provider to associate with Entity class
        """
        self._validate_entity_cls(entity_cls)

        # Register the entity if not registered already
        entity_name = fully_qualified_name(entity_cls)
        provider_name = provider_name or entity_cls.meta_.provider or 'default'

        try:
            entity = self._get_entity_by_class(entity_cls)

            if entity:
                # This probably is an accidental re-registration of the entity
                #   and we should warn the user of a possible repository confusion
                raise ConfigurationError(
                    f'Entity {entity_name} has already been registered')
        except AssertionError:
            # Entity has not been registered yet. Let's go ahead and add it to the registry.
            entity_record = RepositoryFactory.EntityRecord(
                name=entity_cls.__name__,
                qualname=entity_name,
                entity_cls=entity_cls,
                provider_name=provider_name,
                model_cls=None
            )
            self._registry[entity_name] = entity_record
            logger.debug(
                f'Registered entity {entity_name} with provider {provider_name}')

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

    def _validate_entity_cls(self, entity_cls):
        """Validate that Entity is a valid class"""
        # Import here to avoid cyclic dependency
        from protean.core.entity import Entity

        if not issubclass(entity_cls, Entity):
            raise AssertionError(
                f'Entity {entity_cls.__name__} must be subclass of `Entity`')

        if entity_cls.meta_.abstract is True:
            raise NotSupportedError(
                f'{entity_cls.__name__} class has been marked abstract'
                f' and cannot be instantiated')

    def get_model(self, entity_cls):
        """Retrieve Model class connected to Entity"""
        entity_record = self._get_entity_by_class(entity_cls)

        model_cls = None
        if entity_record.model_cls:
            model_cls = entity_record.model_cls
        else:
            # We should ask the Provider to give a fully baked model the first time
            #   that has been initialized properly for this entity
            provider = self.get_provider(entity_record.provider_name)
            baked_model_cls = provider.get_model(entity_record.entity_cls)

            # Record for future reference
            new_entity_record = entity_record._replace(model_cls=baked_model_cls)
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

        return provider.get_repository(entity_record.entity_cls)


repo_factory = RepositoryFactory()
