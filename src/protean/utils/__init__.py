def fetch_entity_cls_from_registry(entity):
        """Util Method to fetch an Entity class from an entity's name"""
        # Defensive check to ensure we only process if `to_cls` is a string
        if isinstance(entity, str):
            from protean.core.repository import repo_factory  # FIXME Move to a better placement

            try:
                return repo_factory.get_entity(entity)
            except AssertionError:
                # Entity has not been registered (yet)
                # FIXME print a helpful debug message
                raise
        else:
            return entity
