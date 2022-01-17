import logging

from collections import defaultdict
from enum import Enum
from typing import Any, Dict

import inflection

from protean.utils import DomainObjects, fully_qualified_name

logger = logging.getLogger(__name__)


class _DomainRegistry:
    class DomainRecord:
        def __init__(self, name: str, qualname: str, class_type: str, cls: Any):
            self.name = name
            self.qualname = qualname
            self.class_type = class_type
            self.cls = cls

    def __init__(self):
        self._elements: Dict[str, dict] = {}
        self._elements_by_name: Dict[str, list] = {}

        # Initialize placeholders for element types
        for element_type in DomainObjects:
            self._elements[element_type.value] = defaultdict(dict)

    def _is_invalid_element_cls(self, element_cls):
        """Ensure that we are dealing with an element class, that:

        * Has a `element_type` attribute
        * `element_type` is an Enum value
        * The value of `element_type` enum is among recognized `DomainObjects` values
        """
        return (
            not hasattr(element_cls, "element_type")
            or not isinstance(element_cls.element_type, Enum)
            or element_cls.element_type.name not in DomainObjects.__members__
        )

    def register_element(self, element_cls):
        if self._is_invalid_element_cls(element_cls):
            raise NotImplementedError

        element_name = fully_qualified_name(element_cls)

        element = self._elements[element_cls.element_type.value][element_name]
        if element:
            # raise ConfigurationError(f'Element {element_name} has already been registered')
            logger.debug(f"Element {element_name} was already in the registry")
        else:
            element_record = _DomainRegistry.DomainRecord(
                name=element_cls.__name__,
                qualname=element_name,
                class_type=element_cls.element_type.value,
                cls=element_cls,
            )

            self._elements[element_cls.element_type.value][
                element_name
            ] = element_record

            # Create an array to hold multiple elements of same name
            if element_cls.__name__ in self._elements_by_name:
                self._elements_by_name[element_cls.__name__].append(element_record)
            else:
                self._elements_by_name[element_cls.__name__] = [element_record]

            logger.debug(
                f"Registered Element {element_name} with Domain as a {element_cls.element_type.value}"
            )

    def delist_element(self, element_cls):
        if self._is_invalid_element_cls(element_cls):
            raise NotImplementedError

        element_name = fully_qualified_name(element_cls)

        self._elements[element_cls.element_type.value].pop(element_name, None)

    def get(self, element_type):
        return self._elements[element_type.value]


# Set up access to all elements as properties
for element_type in DomainObjects:
    """Set up `properties` on Registry

    Since all elements are stored within a Dict in the registry, accessing
    them will mean knowing the storage structure. It is instead preferable to
    expose the elements by their element types as properties.

    Registry object will contain properties named after of each element type
    and pluralized to indicate that all elements of the type will be returned.

    E.g.
    AGGREGATE: registry.aggregates
    VALUE_OBJECT: registry.value_objects
    """

    # Lowercase element type, add underscores and pluralize
    prop_name = inflection.pluralize(inflection.underscore(element_type.value.lower()))

    # This weird syntax is because when using lambdas in a for loop, we need to supply
    #   element_type as an argument with a default value of element_type
    prop = property(
        lambda self, element_type=element_type: self.get(element_type)
    )  # pragma: no cover  # FIXME Is it possible to cover this line in tests

    # Set the property on the class
    setattr(_DomainRegistry, prop_name, prop)
