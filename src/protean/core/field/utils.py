""" Utility functions for the Field Module """


def fetch_entity_cls_from_registry(entity):
    """Util Method to fetch an Entity class from an entity's name"""
    from protean.core.repository.factory import repo_factory

    # Defensive check to ensure we only process if `to_cls` is a string
    if isinstance(entity, str):
        try:
            return repo_factory.get_entity(entity)
        except AssertionError:
            # Entity has not been registered (yet)
            # FIXME print a helpful debug message
            raise
    else:
        return entity


def fetch_value_object_cls_from_domain(value_object_name):
    """Util Method to fetch an Value Object class from a name string"""
    # Defensive check to ensure we only process if `value_object_cls` is a string
    if isinstance(value_object_name, str):
        try:
            from protean import domain_registry
            return domain_registry.get_value_object_by_name(value_object_name)
        except AssertionError:
            # Value Object has not been registered (yet)
            # FIXME print a helpful debug message
            raise
    else:
        return value_object_name
