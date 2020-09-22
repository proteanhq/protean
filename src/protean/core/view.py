"""View Functionality and Classes"""
# Standard Library Imports
import logging

# Protean
from protean.core.entity import BaseEntity
from protean.core.exceptions import NotSupportedError
from protean.utils import DomainObjects, derive_element_class

logger = logging.getLogger("protean.domain.view")


class BaseView(BaseEntity):
    """The Base class for Protean-Compliant Domain Views.

    Provides helper methods to custom define aggregate attributes, and query attribute names
    during runtime.

    Basic Usage::

        @domain.view
        class Dog:
            id = field.Integer(identifier=True)
            name = field.String(required=True, max_length=50)
            age = field.Integer(default=5)
            owner = field.String(required=True, max_length=15)

    (or)

        class Dog(BaseView):
            id = field.Integer(identifier=True)
            name = field.String(required=True, max_length=50)
            age = field.Integer(default=5)
            owner = field.String(required=True, max_length=15)

        domain.register_element(Dog)

    During persistence, the model associated with this entity is retrieved dynamically from
            the repository factory. Model is usually initialized with a live DB connection.
    """

    element_type = DomainObjects.VIEW

    def __new__(cls, *args, **kwargs):
        if cls is BaseView:
            raise TypeError("BaseView cannot be instantiated")
        return super().__new__(cls)


def view_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseView)

    if element_cls.meta_.abstract is True:
        raise NotSupportedError(
            f"{element_cls.__name__} class has been marked abstract"
            f" and cannot be instantiated"
        )

    element_cls.meta_.provider = (
        kwargs.pop("provider", None)
        or (hasattr(element_cls, "meta_") and element_cls.meta_.provider)
        or "default"
    )
    element_cls.meta_.model = (
        kwargs.pop("model", None)
        or (hasattr(element_cls, "meta_") and element_cls.meta_.model)
        or None
    )

    return element_cls
