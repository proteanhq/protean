# Standard Library Imports
import logging

from abc import ABCMeta, abstractmethod

logger = logging.getLogger("protean.repository")


class BaseLookup(metaclass=ABCMeta):
    """Base Lookup class to implement for each lookup

    Inspired by the lookup mechanism implemented in Django.

    Each lookup, which is simply a data comparison (like `name == 'John'`), is implemented as a subclass of this
    class, and has to implement the `as_expression()` method to provide the representation that the persistence
    store needs.

    Lookups are identified by their names, and the names are stored in the `lookup_name` class variable.
    """

    lookup_name = None

    def __init__(self, source, target):
        """Source is LHS and Target is RHS of a comparsion.

        For example, in the expression `name == 'John'`, `name` is source (LHS) and `'John'` is target (RHS).
        In other words, source is the key/column/attribute to be searched on, and target is the value present in the
        persistent store.
        """
        self.source, self.target = source, target

    def process_source(self):
        """This is a blank implementation that simply returns the source.

        Returns `source` (LHS of the expression).

        You can override this method to manipulate the source when necessary. For example, if you are using a
        data store that cannot perform case-insensitive queries, it may be useful to always compare in lowercase.
        """
        return self.source

    def process_target(self):
        """This is a blank implementation that simply returns the target.

        Returns `target` (RHS of the expression).

        You can override this method to manipulate the target when necessary. A good example of overriding this
        method is when you are using a data store that needs strings to be enclosed in single quotes.
        """
        return self.target

    @abstractmethod
    def as_expression(self):
        """This methods should return the source and the target in the format required by the persistence store.

        Concrete implementation for this method varies from database to database.
        """
        raise NotImplementedError
