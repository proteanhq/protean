import inspect
import logging

from collections import defaultdict
from functools import wraps
from typing import List, Union

from protean import BaseAggregate
from protean.container import Element, OptionsMixin
from protean.exceptions import IncorrectUsageError, ValidationError
from protean.utils import DomainObjects, derive_element_class

logger = logging.getLogger(__name__)


class BaseDomainService(Element, OptionsMixin):
    """Base DomainService class that all other domain services should inherit from.

    This is a placeholder class for now. Methods that are implemented
    in concreate Domain Service classes are inspired from Domain concepts,
    and typically use more than one aggregate to accomplish a task"""

    element_type = DomainObjects.DOMAIN_SERVICE

    class Meta:
        abstract = True

    def __new__(cls, *args, **kwargs):
        if cls is BaseDomainService:
            raise TypeError("BaseDomainService cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls):
        return [
            ("part_of", None),
        ]

    def __init_subclass__(subclass) -> None:
        super().__init_subclass__()

        # Record invariant methods
        setattr(subclass, "_invariants", defaultdict(dict))

    def __init__(self, *aggregates: Union[BaseAggregate, List[BaseAggregate]]):
        """
        Initializes a DomainService with one or more aggregates.

        Args:
            *aggregates (Union[BaseAggregate, List[BaseAggregate]]): One or more aggregates to be associated with this
            DomainService.
        """
        self._aggregates = aggregates


def wrap_call_method_with_invariants(cls):
    """
    Wraps the __call__ method of a class with a function that executes the original __call__ method and then runs
    any defined invariant methods on the object. If any of the invariant methods raise a `ValidationError`,
    the wrapped `__call__` method will raise a ValidationError with the collected error messages.
    """

    # Protect against re-wrapping
    #   by checking whether __call__ has `__wrapped__` attribute
    #   which it would if it has been wrapped already
    #
    # FIXME Is there a better way to prevent re-wrapping the same class?
    if not hasattr(cls.__call__, "__wrapped__"):
        original_call = cls.__call__

        @wraps(original_call)
        def wrapped_call(self, *args, **kwargs):
            # Run the invariant methods marked `pre` before the original __call__ method
            errors = {}
            for invariant_method in self._invariants["pre"].values():
                try:
                    invariant_method(self)
                except ValidationError as err:
                    for field_name in err.messages:
                        if field_name not in errors:
                            errors[field_name] = []
                        errors[field_name].extend(err.messages[field_name])

            if errors:
                raise ValidationError(errors)

            # Execute the original __call__ method
            result = original_call(self, *args, **kwargs)

            # Run the invariant methods marked `post` after the original __call__ method
            for invariant_method in self._invariants["post"].values():
                try:
                    invariant_method(self)
                except ValidationError as err:
                    for field_name in err.messages:
                        if field_name not in errors:
                            errors[field_name] = []
                        errors[field_name].extend(err.messages[field_name])

            if errors:
                raise ValidationError(errors)

            return result

        cls.__call__ = wrapped_call
    return cls


def domain_service_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseDomainService, **kwargs)

    if not element_cls.meta_.part_of or len(element_cls.meta_.part_of) < 2:
        raise IncorrectUsageError(
            {
                "_entity": [
                    f"Domain Service `{element_cls.__name__}` needs to be associated with two or more Aggregates"
                ]
            }
        )

    # Iterate through methods marked as `@invariant` and record them for later use
    methods = inspect.getmembers(element_cls, predicate=inspect.isroutine)
    for method_name, method in methods:
        if not (
            method_name.startswith("__") and method_name.endswith("__")
        ) and hasattr(method, "_invariant"):
            element_cls._invariants[method._invariant][method_name] = method

    # Wrap the __call__ method with invariant checks
    element_cls = wrap_call_method_with_invariants(element_cls)

    return element_cls
