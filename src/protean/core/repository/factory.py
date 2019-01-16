""" Factory class for managing repository connections"""
import importlib
import logging
from threading import local

from protean.conf import active_config
from protean.core.exceptions import ConfigurationError

from .base import BaseAdapter
from .base import BaseModel

logger = logging.getLogger('protean.repository')


class RepositoryFactory:
    """Repository Factory interface to retrieve Resource Objects from Repositories

    FIXME RepositoryFactory should prepare adapter objects JIT, so that connections
        are kept open only for the necessary duration. Once the request is handled, it should
        be let go.
    """

    def __init__(self):
        """"Initialize repository factory"""
        self._registry = {}
        self._model_registry = {}
        self._connections = local()
        self._repositories = None

    @property
    def repositories(self):
        """ Return the databases configured for the application"""
        if self._repositories is None:
            self._repositories = active_config.REPOSITORIES

        if not isinstance(self._repositories, dict) or self._repositories == {}:
            raise ConfigurationError(
                "'REPOSITORIES' config must be a dict and at least one "
                "database must be defined")

        if 'default' not in self._repositories:
            raise ConfigurationError(
                "You must define a 'default' repository")

        return self._repositories

    @property
    def connections(self):
        """ Return the registered repository connections"""
        try:
            return self._connections.connections
        except AttributeError:
            self._connections.connections = {}
            return self._connections.connections

    def register(self, model_cls, repo_cls=None):
        """ Register the given model with the factory
        :param model_cls: class of the model to be registered
        :param repo_cls: Optional repository class to use if not the
        `Repository` defined by the provider is userd
        """
        if not issubclass(model_cls, BaseModel):
            raise AssertionError(
                f'Model {model_cls} must be subclass of `BaseModel`')

        if repo_cls and not issubclass(repo_cls, BaseAdapter):
            raise AssertionError(
                f'Repository {repo_cls} must be subclass of `BaseAdapter`')

        # Register the model if it does not exist
        model_name = model_cls.__name__
        entity_name = model_cls.Meta.entity.__name__
        if not self._registry.get(entity_name):
            # Lookup the connection details for the model
            try:
                conn_info = self.repositories[model_cls.opts_.bind]
            except KeyError:
                raise ConfigurationError(
                    f"'{model_cls.opts_.bind}' repository not found in "
                    f"'REPOSITORIES'")

            # Load the repository provider
            provider = importlib.import_module(conn_info['PROVIDER'])

            # If no connection exists then build it
            if model_cls.opts_.bind not in self.connections:
                conn_handler = provider.ConnectionHandler(
                    model_cls.opts_.bind, conn_info)
                self._connections.connections[model_cls.opts_.bind] = \
                    conn_handler.get_connection()

            # Finally register the model against the provider repository
            repo_cls = repo_cls or provider.Adapter
            self._registry[entity_name] = \
                repo_cls(self.connections[model_cls.opts_.bind], model_cls)
            self._model_registry[entity_name] = model_cls
            logger.debug(
                f'Registered model {model_name} for entity {entity_name} with repository provider '
                f'{conn_info["PROVIDER"]}.')

    def get_model(self, entity_name):
        """Retrieve Model class connected to Entity"""
        try:
            return self._model_registry[entity_name]
        except KeyError:
            raise AssertionError('No Model registered for {entity_name}')

    def __getattr__(self, entity_name):
        try:
            return self._registry[entity_name]
        except KeyError:
            raise AssertionError('No Model registered for {entity_name}')

    def close_connections(self):
        """ Close all connections registered with the repository """
        for conn_name, conn_obj in self.connections.items():
            conn_info = self.repositories[conn_name]
            provider = importlib.import_module(conn_info['PROVIDER'])
            conn_handler = provider.ConnectionHandler(conn_name, conn_info)
            conn_handler.close_connection(conn_obj)


repo_factory = RepositoryFactory()
