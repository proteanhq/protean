""" Utility functions for the Field Module """
# Protean
from protean.domain import DomainObjects
from protean.globals import current_domain


def fetch_entity_cls_from_registry(entity):
    """Util Method to fetch an Entity class from an entity's name"""
    # Defensive check to ensure we only process if `to_cls` is a string
    if isinstance(entity, str):
        try:
            return current_domain._get_element_by_name(
                (DomainObjects.AGGREGATE, DomainObjects.ENTITY), entity
            ).cls
        except AssertionError:
            # Entity has not been registered (yet)
            # FIXME print a helpful debug message
            raise
    else:
        return entity


def fetch_value_object_cls_from_domain(value_object):
    """Util Method to fetch an Value Object class from a name string"""
    # Defensive check to ensure we only process if `value_object_cls` is a string
    if isinstance(value_object, str):
        try:
            return current_domain._get_element_by_name(
                DomainObjects.VALUE_OBJECT, value_object
            ).cls
        except AssertionError:
            # Value Object has not been registered (yet)
            # FIXME print a helpful debug message
            raise
    else:
        return value_object


def fetch_aggregate_cls_from_domain(aggregate):
    """Util Method to fetch an Aggregate class from a name string"""
    # Defensive check to ensure we only process if `aggregate_cls` is a string
    if isinstance(aggregate, str):
        try:
            return current_domain._get_element_by_name(
                DomainObjects.AGGREGATE, aggregate
            ).cls
        except AssertionError:
            # Aggregate has not been registered (yet)
            # FIXME print a helpful debug message
            raise
    else:
        return aggregate


def fetch_entity_cls_from_domain(entity):
    """Util Method to fetch an Entity class from a name string"""
    # Defensive check to ensure we only process if `entity_cls` is a string
    if isinstance(entity, str):
        try:
            return current_domain._get_element_by_name(DomainObjects.ENTITY, entity).cls
        except AssertionError:
            # Entity has not been registered (yet)
            # FIXME print a helpful debug message
            raise
    else:
        return entity
