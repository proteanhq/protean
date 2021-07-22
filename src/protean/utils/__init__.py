"""Utility module for Protean

Definitions/declaractions in this module should be independent of other modules,
to the maximum extent possible.
"""
import functools
import logging

from enum import Enum, auto
from uuid import uuid4

from protean.core.exceptions import IncorrectUsageError, ConfigurationError
from protean.globals import current_domain

logger = logging.getLogger("protean.utils")


class IdentityStrategy(Enum):
    UUID = auto()
    DATABASE = auto()
    FUNCTION = auto()


class IdentityType(Enum):
    INTEGER = "INTEGER"
    STRING = "STRING"
    UUID = "UUID"


class EventStrategy(Enum):
    DB_SUPPORTED = "DB_SUPPORTED"
    NAIVE = "NAIVE"


class Database(Enum):
    ELASTICSEARCH = "ELASTICSEARCH"
    MEMORY = "MEMORY"
    POSTGRESQL = "POSTGRESQL"
    SQLITE = "SQLITE"


class Cache(Enum):
    MEMORY = "MEMORY"


def fully_qualified_name(cls):
    """Return Fully Qualified name along with module"""
    return ".".join([cls.__module__, cls.__name__])


def singleton(cls):
    """Make a class a Singleton class (only one instance)"""

    @functools.wraps(cls)
    def wrapper_singleton(*args, **kwargs):
        if not wrapper_singleton.instance:
            wrapper_singleton.instance = cls(*args, **kwargs)
        return wrapper_singleton.instance

    wrapper_singleton.instance = None
    return wrapper_singleton


def convert_str_values_to_list(value):
    if not value:
        return []
    elif isinstance(value, str):
        return [value]
    else:
        return list(value)


class DomainObjects(Enum):
    AGGREGATE = "AGGREGATE"
    APPLICATION_SERVICE = "APPLICATION_SERVICE"
    COMMAND = "COMMAND"
    COMMAND_HANDLER = "COMMAND_HANDLER"
    EVENT = "EVENT"
    DOMAIN_SERVICE = "DOMAIN_SERVICE"
    EMAIL = "EMAIL"
    ENTITY = "ENTITY"
    MODEL = "MODEL"
    REPOSITORY = "REPOSITORY"
    SERIALIZER = "SERIALIZER"
    SUBSCRIBER = "SUBSCRIBER"
    VALUE_OBJECT = "VALUE_OBJECT"
    VIEW = "VIEW"


def derive_element_class(element_cls, base_cls):
    if not issubclass(element_cls, base_cls):
        try:
            new_dict = element_cls.__dict__.copy()
            new_dict.pop("__dict__", None)  # Remove __dict__ to prevent recursion

            element_cls = type(element_cls.__name__, (base_cls,), new_dict)
        except BaseException as exc:
            logger.debug("Error during Element registration:", repr(exc))
            raise IncorrectUsageError(
                "Invalid class {element_cls.__name__} for type {element_type.value}"
                " (Error: {exc})",
            )

    return element_cls


def generate_identity():
    """Generate Unique Identifier, based on configured strategy"""
    if current_domain.config["IDENTITY_STRATEGY"] == IdentityStrategy.UUID:
        if current_domain.config["IDENTITY_TYPE"] == IdentityType.INTEGER:
            return uuid4().int
        elif current_domain.config["IDENTITY_TYPE"] == IdentityType.STRING:
            return str(uuid4())
        elif current_domain.config["IDENTITY_TYPE"] == IdentityType.UUID:
            return uuid4()
        else:
            raise ConfigurationError(
                f'Unknown Identity Type {current_domain.config["IDENTITY_TYPE"]}'
            )

    return None  # Database will generate the identity


def fetch_entity_cls_from_registry(entity):
    """Util Method to fetch an Entity class from an entity's name"""
    # Defensive check to ensure we only process if `to_cls` is a string
    if isinstance(entity, str):
        try:
            # Try fetching by class name
            return current_domain._get_element_by_name(
                (DomainObjects.AGGREGATE, DomainObjects.ENTITY), entity
            ).cls
        except ConfigurationError:
            try:
                # Try fetching by fully qualified class name
                return current_domain._get_element_by_fully_qualified_name(
                    (DomainObjects.AGGREGATE, DomainObjects.ENTITY), entity
                ).cls
            except AssertionError:
                # Entity has not been registered
                # FIXME print a helpful debug message
                raise
    else:
        # FIXME Check if entity is subclassed from BaseEntity
        return entity


def fetch_event_cls_from_registry(event_cls):
    """Util Method to fetch an Event class from an event's name"""
    # FIXME Generalize these fucntions
    if isinstance(event_cls, str):
        try:
            # Try fetching by class name
            return current_domain._get_element_by_name(
                (DomainObjects.EVENT,), event_cls
            ).cls
        except ConfigurationError:
            try:
                # Try fetching by fully qualified class name
                return current_domain._get_element_by_fully_qualified_name(
                    (DomainObjects.EVENT,), event_cls
                ).cls
            except AssertionError:
                # Event has not been registered
                # FIXME print a helpful debug message
                raise
    else:
        # FIXME Check if entity is subclassed from BaseEvent
        return event_cls


def fetch_command_cls_from_registry(command_cls):
    """Util Method to fetch an Command class from an command's name"""
    if isinstance(command_cls, str):
        try:
            # Try fetching by class name
            return current_domain._get_element_by_name(
                (DomainObjects.COMMAND,), command_cls
            ).cls
        except ConfigurationError:
            try:
                # Try fetching by fully qualified class name
                return current_domain._get_element_by_fully_qualified_name(
                    (DomainObjects.COMMAND,), command_cls
                ).cls
            except AssertionError:
                # Event has not been registered
                # FIXME print a helpful debug message
                raise
    else:
        # FIXME Check if entity is subclassed from BaseCommand
        return command_cls


def fetch_value_object_cls_from_domain(value_object):
    """Util Method to fetch an Value Object class from a name string"""
    # Defensive check to ensure we only process if `value_object_cls` is a string
    if isinstance(value_object, str):
        try:
            return current_domain._get_element_by_fully_qualified_name(
                DomainObjects.VALUE_OBJECT, value_object
            ).cls
        except AssertionError:
            # Value Object has not been registered (yet)
            # FIXME print a helpful debug message
            raise
    else:
        return value_object
