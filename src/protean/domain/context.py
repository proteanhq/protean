"""Context Management Framework"""
import logging
import sys

from protean.globals import _domain_context_stack

# a singleton sentinel value for parameter defaults
_sentinel = object()

logger = logging.getLogger("protean.application")


class _DomainContextGlobals(object):
    """A plain object. Used as a namespace for storing data during an
    domain context.

    Creating a domain context automatically creates this object, which is
    made available as the :data:`g` proxy.
    """

    def get(self, name, default=None):
        """Get an attribute by name, or a default value. Like
        :meth:`dict.get`.

        :param name: Name of attribute to get.
        :param default: Value to return if the attribute is not present.
        """
        return self.__dict__.get(name, default)

    def pop(self, name, default=_sentinel):
        """Get and remove an attribute by name. Like :meth:`dict.pop`.

        :param name: Name of attribute to pop.
        :param default: Value to return if the attribute is not present,
            instead of raise a ``KeyError``.
        """
        if default is _sentinel:
            return self.__dict__.pop(name)
        else:
            return self.__dict__.pop(name, default)

    def setdefault(self, name, default=None):
        """Get the value of an attribute if it is present, otherwise
        set and return a default value. Like :meth:`dict.setdefault`.

        :param name: Name of attribute to get.
        :param: default: Value to set and return if the attribute is not
            present.
        """
        return self.__dict__.setdefault(name, default)

    def __contains__(self, item):
        return item in self.__dict__

    def __iter__(self):
        return iter(self.__dict__)

    def __repr__(self):
        top = _domain_context_stack.top
        if top is not None:
            return "<protean.g of %r>" % top.domain.domain_name
        return object.__repr__(self)


def has_domain_context():
    """If you have code that wants to test if a domain context is there or
    not this function can be used.  You can also just do a boolean check on the
    :data:`current_domain` object instead.
    """
    return _domain_context_stack.top is not None


class DomainContext(object):
    """The domain context binds an domain object implicitly
    to the current thread or greenlet.
    """

    def __init__(self, domain):
        self.domain = domain
        self.g = domain.domain_context_globals_class()

        # Use a basic "refcount" to track number of domain contexts
        self._ref_count = 0

    def push(self):
        """Binds the domain context to the current context."""
        self._ref_count += 1
        if hasattr(sys, "exc_clear"):
            sys.exc_clear()
        _domain_context_stack.push(self)

    def pop(self, exc=_sentinel):
        """Pops the domain context."""
        try:
            self._ref_count -= 1
            if self._ref_count <= 0:
                if exc is _sentinel:
                    exc = sys.exc_info()[1]
                self.domain.do_teardown_domain_context(exc)
        finally:
            rv = _domain_context_stack.pop()
        assert rv is self, "Popped wrong domain context.  (%r instead of %r)" % (
            rv,
            self,
        )

    def __enter__(self):
        self.push()
        return self

    def __exit__(self, exc_type, exc_value, tb):
        self.pop(exc_value)

        if exc_type is not None:
            raise (exc_type, exc_value, tb)
