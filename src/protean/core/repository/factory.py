""" Factory class for managing repository connections"""
import logging
import importlib

from protean.core.exceptions import ConfigurationError
from protean.conf import active_config
from .base import RepositorySchema, BaseRepository

logger = logging.getLogger('protean.repository')


class RepositoryFactory:
    """Repository Factory interface to retrieve resource repositories"""

    def __init__(self):
        """"Initialize repository factory"""
        self._registry = {}
        self._connections = {}
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

    def register(self, schema_cls, repo_cls=None):
        """ Register the given schema with the factory
        :param schema_cls: class of the schema to be registered
        :param repo_cls: Optional repository class to use if not the
        `Repository` defined by the provider is userd
        """
        if not issubclass(schema_cls, RepositorySchema):
            raise AssertionError(
                f'Schema {schema_cls} must be subclass of `RepositorySchema`')

        if repo_cls and not issubclass(repo_cls, BaseRepository):
            raise AssertionError(
                f'Repository {repo_cls} must be subclass of `BaseRepository`')

        # Register the schema if it does not exist
        schema_name = schema_cls.__name__
        if schema_name not in self._registry:
            # Lookup the connection details for the schema
            try:
                conn_info = self.repositories[schema_cls.opts.bind]
            except KeyError:
                raise ConfigurationError(
                    f"'{schema_cls.opts.bind}' repository not found in "
                    f"'REPOSITORIES'")

            # Load the repository provider
            provider = importlib.import_module(conn_info['PROVIDER'])

            # If no connection exists then build it
            if schema_cls.opts.bind not in self._connections:
                conn_handler = provider.ConnectionHandler(conn_info)
                self._connections[schema_cls.opts.bind] = \
                    conn_handler.get_connection()

            # Finally register the schema against the provider repository
            repo_cls = repo_cls or provider.Repository
            self._registry[schema_name] = repo_cls(
                self._connections[schema_cls.opts.bind], schema_cls)
            logger.debug(
                f'Registered schema {schema_name} with repository provider '
                f'{conn_info["PROVIDER"]}.')

    def __getattr__(self, schema):
        try:
            return self._registry[schema]
        except KeyError:
            raise AssertionError('Unregistered Schema')


rf = RepositoryFactory()
