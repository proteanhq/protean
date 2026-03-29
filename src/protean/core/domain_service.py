import inspect
import logging
from collections import defaultdict
from functools import wraps
from typing import Any, Callable, List, TypeVar, Union

from protean.core.aggregate import BaseAggregate
from protean.exceptions import IncorrectUsageError, NotSupportedError, ValidationError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import Element, OptionsMixin

logger = logging.getLogger(__name__)


class BaseDomainService(Element, OptionsMixin):
    """Base class for domain services that encapsulate business logic spanning
    multiple aggregates.

    Domain services are stateless, instantiated with the aggregate instances
    they operate on, and must be associated with two or more aggregates via
    the ``part_of`` option. Public methods (including ``__call__``) are
    automatically wrapped with pre/post invariant checks when the service
    class has methods decorated with ``@invariant.pre`` or ``@invariant.post``.

    **Meta Options**

    | Option | Type | Description |
    |--------|------|-------------|
    | ``part_of`` | ``list`` | List of two or more aggregate classes this service operates on. Required. |

    Example::

        @domain.domain_service(part_of=[Order, Inventory])
        class PlaceOrderService(BaseDomainService):

            @invariant.post
            def order_should_have_items(self):
                if not self._aggregates[0].items:
                    raise ValidationError({"items": ["Order must have items"]})

            def __call__(self):
                order, inventory = self._aggregates
                inventory.reserve(order.items)
                order.confirm()
    """

    element_type = DomainObjects.DOMAIN_SERVICE

    def __new__(cls, *args, **kwargs):
        if cls is BaseDomainService:
            raise NotSupportedError("BaseDomainService cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls):
        return [
            ("part_of", None),
        ]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        # Record invariant methods
        setattr(cls, "_invariants", defaultdict(dict))

    def __init__(self, *aggregates: Union[BaseAggregate, List[BaseAggregate]]):
        """Initialize a DomainService with one or more aggregates.

        Args:
            *aggregates: One or more aggregates to operate on.
        """
        self._aggregates = aggregates


def _make_invariant_wrapper(original_method: Callable) -> Callable:
    """Create an invariant-checking wrapper for a single domain service method.

    Extracted as a function so that ``original_method`` is captured by value
    (as a parameter), avoiding the classic closure-in-loop bug.
    """

    @wraps(original_method)
    def wrapped_call(self: "BaseDomainService", *args: Any, **kwargs: Any) -> Any:
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

        result = original_method(self, *args, **kwargs)

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

    return wrapped_call


def wrap_methods_with_invariant_calls(cls):
    """
    Case: When Domain Service is defined as a regular instantiable class.

    This method wraps every defined domain service method with a function that checks invariants around the original
    method. If any of the invariant methods raise a `ValidationError`, the wrapped `__call__` method will raise a
    ValidationError with the collected error messages.
    """
    for method_name, method in inspect.getmembers(cls, predicate=inspect.isroutine):
        if (
            not (method_name.startswith("__") and method_name.endswith("__"))
            and not method_name.startswith("_")
        ) or method_name == "__call__":
            # `@wraps` sets `__wrapped__` on the wrapper, so its presence
            # means this method was already wrapped in a prior factory call.
            if not hasattr(method, "__wrapped__"):
                setattr(cls, method_name, _make_invariant_wrapper(method))

    return cls


_T = TypeVar("_T")


def domain_service_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
    element_cls = derive_element_class(element_cls, BaseDomainService, **opts)

    if not element_cls.meta_.part_of or len(element_cls.meta_.part_of) < 2:
        raise IncorrectUsageError(
            f"Domain Service `{element_cls.__name__}` needs to be associated with two or more Aggregates"
        )

    # Iterate through methods marked as `@invariant` and record them for later use
    methods = inspect.getmembers(element_cls, predicate=inspect.isroutine)
    for method_name, method in methods:
        if not (
            method_name.startswith("__") and method_name.endswith("__")
        ) and hasattr(method, "_invariant"):
            element_cls._invariants[method._invariant][method_name] = method

    element_cls = wrap_methods_with_invariant_calls(element_cls)

    return element_cls
