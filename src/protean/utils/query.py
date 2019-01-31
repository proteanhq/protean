"""Utility classes and methods for DB Adapters and Query Constructors"""
import functools
import inspect


def subclasses(cls):
    """Iterator utilty to loop and clear registered Lookups against a class"""
    yield cls
    for subclass in cls.__subclasses__():
        yield from subclasses(subclass)


class RegisterLookupMixin:
    """Helper Mixin to register Lookups to an Adapter"""
    @classmethod
    def _get_lookup(cls, lookup_name):
        return cls.get_lookups().get(lookup_name, None)

    @classmethod
    @functools.lru_cache(maxsize=None)
    def get_lookups(cls):
        """Fetch all Lookups"""
        class_lookups = [parent.__dict__.get('class_lookups', {}) for parent in inspect.getmro(cls)]
        return cls.merge_dicts(class_lookups)

    def get_lookup(self, lookup_name):
        """Fetch Lookup by name"""
        from protean.core.repository import Lookup
        lookup = self._get_lookup(lookup_name)

        # If unable to find Lookup, or if Lookup is the wrong class, raise Error
        if lookup is None or (lookup is not None and not issubclass(lookup, Lookup)):
            raise NotImplementedError

        return lookup

    @staticmethod
    def merge_dicts(dicts):
        """
        Merge dicts in reverse to preference the order of the original list. e.g.,
        merge_dicts([a, b]) will preference the keys in 'a' over those in 'b'.
        """
        merged = {}
        for d in reversed(dicts):
            merged.update(d)
        return merged

    @classmethod
    def _clear_cached_lookups(cls):
        for subclass in subclasses(cls):
            subclass.get_lookups.cache_clear()

    @classmethod
    def register_lookup(cls, lookup, lookup_name=None):
        """Register a Lookup to a class"""
        if lookup_name is None:
            lookup_name = lookup.lookup_name
        if 'class_lookups' not in cls.__dict__:
            cls.class_lookups = {}

        cls.class_lookups[lookup_name] = lookup
        cls._clear_cached_lookups()

        return lookup

    @classmethod
    def _unregister_lookup(cls, lookup, lookup_name=None):
        """
        Remove given lookup from cls lookups. For use in tests only as it's
        not thread-safe.
        """
        if lookup_name is None:
            lookup_name = lookup.lookup_name
        del cls.class_lookups[lookup_name]
