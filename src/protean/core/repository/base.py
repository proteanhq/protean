""" Define the interfaces for Repository implementations """
import logging
from abc import ABCMeta
from abc import abstractmethod
from typing import Any

from protean.core.exceptions import ConfigurationError
from protean.utils import inflection
from protean.utils.query import Q
from protean.utils.query import RegisterLookupMixin

from .factory import repo_factory
from .pagination import Pagination

logger = logging.getLogger('protean.repository')


class BaseAdapter(RegisterLookupMixin, metaclass=ABCMeta):
    """Adapter interface to interact with databases

    :param conn: A connection/session to the data source of the model
    :param model_cls: The model class registered with this repository
    """

    def __init__(self, conn, model_cls):
        self.conn = conn
        self.model_cls = model_cls
        self.entity_cls = model_cls.opts_.entity_cls
        self.model_name = model_cls.opts_.model_name

    def _extract_lookup(self, key):
        """Extract lookup method based on key name format"""
        parts = key.split('__')
        # 'exact' is the default lookup if there was no explicit comparison op in `key`
        #   Assume there is only one `__` in the key.
        #   FIXME Change for child attribute query support
        op = 'exact' if len(parts) == 1 else parts[1]

        # Construct and assign the lookup class as a filter criteria
        return parts[0], self.get_lookup(op)

    @abstractmethod
    def _filter_objects(self, criteria: Q, page: int = 1, per_page: int = 10,
                        order_by: list = ()) -> Pagination:
        """
        Filter objects from the repository. Method must return a `Pagination`
        object
        """

    @abstractmethod
    def _create_object(self, model_obj: Any):
        """Create a new model object from the entity"""

    @abstractmethod
    def _update_object(self, model_obj: Any):
        """Update a model object in the repository and return it"""

    @abstractmethod
    def _delete_objects(self, **filters):
        """Delete a Record from the Repository"""


class ModelOptions(object):
    """class Meta options for the :class:`BaseModel`."""

    def __init__(self, meta, model_cls):
        self.entity_cls = getattr(meta, 'entity', None)

        # Import here to avoid cyclic deps
        from protean.core.entity import Entity
        if not self.entity_cls or not issubclass(self.entity_cls, Entity):
            raise ConfigurationError(
                '`entity` option must be set and be a subclass of `Entity`.')

        # Get the model name to be used, if not provided default it
        self.model_name = getattr(meta, 'model_name', None)
        if not self.model_name:
            self.model_name = inflection.underscore(model_cls.__name__)

        # Get the database bound to this model
        self.bind = getattr(meta, 'bind', 'default')

        # Default ordering of the filter response
        self.order_by = getattr(meta, 'order_by', ())


class BaseModelMeta(ABCMeta):
    """ Metaclass for the BaseModel, sets options and registers the model """
    def __new__(mcs, name, bases, attrs):
        klass = super().__new__(mcs, name, bases, attrs)

        # Get the Meta class attribute defined for the base class
        meta = getattr(klass, 'Meta', None)

        # Load the meta class attributes for non base schemas
        is_base = getattr(meta, 'base', False)
        if not is_base:
            # Set klass.opts by initializing the `options_cls` with the meta
            klass.opts_ = klass.options_cls(meta, klass)
            # Register this model with the factory
            repo_factory.register(klass)

        return klass


class BaseModel(metaclass=BaseModelMeta):
    """Model that defines an index/table in the repository"""
    options_cls = ModelOptions
    opts_ = None

    class Meta(object):
        """Options object for a Model.
        Example usage: ::
            class Meta:
                entity = Dog
        Available options:
        - ``base``: Indicates that this is a base model so ignore the meta
        - ``entity``: the entity associated with this model.
        - ``model_name``: name of this model that will be used as table/index
        names, defaults to underscore version of the class name.
        - ``bind``: the name of the repository connection associated with this
        model, default value is `default`.
        - ``order_by``: default ordering of objects returned by filter queries.
        """
        base = True

    @classmethod
    def from_entity(cls, entity):
        """Initialize Repository Model object from Entity object"""
        raise NotImplementedError()

    @classmethod
    def to_entity(cls, *args, **kwargs):
        """Convert Repository Model Object to Entity Object"""
        raise NotImplementedError()


class BaseConnectionHandler(metaclass=ABCMeta):
    """ Interface to manage connections to the database """

    @abstractmethod
    def get_connection(self):
        """ Get the connection object for the repository"""

    @abstractmethod
    def close_connection(self, conn):
        """ Close the connection object for the repository"""


class Lookup(metaclass=ABCMeta):
    """Base Lookup class to implement in Adapters"""
    lookup_name = None

    def __init__(self, source, target):
        """Source is LHS and Target is RHS of a comparsion"""
        self.source, self.target = source, target

    def process_source(self):
        """Blank implementation; returns source"""
        return self.source

    def process_target(self):
        """Blank implementation; returns target"""
        return self.target

    @abstractmethod
    def as_expression(self):
        """To be implemented in each Adapter for its Lookups"""
        raise NotImplementedError
