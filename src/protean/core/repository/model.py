""" Module containing Model related Class Definitions """

from abc import ABCMeta

from protean.core.exceptions import ConfigurationError
from protean.utils import inflection


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
