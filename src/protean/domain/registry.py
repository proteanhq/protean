import logging
from collections import defaultdict
from enum import Enum
from typing import Any, Dict

import inflection

from protean.exceptions import NotSupportedError
from protean.utils import DomainObjects, fully_qualified_name

logger = logging.getLogger(__name__)


# Define property names for each element type
def properties() -> Dict[str, str]:
    """Properties are named after of each element type and pluralized to
    indicate that all elements of the type will be returned.

    E.g.
    AGGREGATE: registry.aggregates
    VALUE_OBJECT: registry.value_objects

    Returns:
        Dict[str, str]: Dict[pluralized_name, element_type], a dictionary of element type names and their values.
        E.g.
            {
                'aggregates': 'AGGREGATE',
                'entities': 'ENTITY',
                ...
            }
    """
    props = {}
    for element_type in DomainObjects:
        # Lowercase element type, add underscores and pluralize
        prop_name = inflection.pluralize(
            inflection.underscore(element_type.value.lower())
        )
        props[prop_name] = element_type.value

    return props


class _DomainRegistry:
    class DomainRecord:
        def __init__(self, name: str, qualname: str, class_type: str, cls: Any):
            self.name = name
            self.qualname = qualname
            self.class_type = class_type
            self.cls = cls

        def __repr__(self):
            return f"<class {self.name}: {self.qualname} ({self.class_type})>"

    def __init__(self):
        self._elements: Dict[str, dict] = {}
        self._elements_by_name: Dict[str, list] = {}

        # Initialize placeholders for element types
        for element_type in DomainObjects:
            self._elements[element_type.value] = defaultdict(dict)

    def _reset(self):
        for element_type in DomainObjects:
            self._elements[element_type.value] = defaultdict(dict)
        self._elements_by_name: Dict[str, list] = {}

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
            raise NotSupportedError(
                f"Element `{element_cls.__name__}` is not a valid element class"
            )

        # Element name is always the fully qualified name of the class
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

            self._elements[element_cls.element_type.value][element_name] = (
                element_record
            )

            # Create an array to hold multiple elements of same name
            if element_cls.__name__ in self._elements_by_name:
                self._elements_by_name[element_cls.__name__].append(element_record)
            else:
                self._elements_by_name[element_cls.__name__] = [element_record]

            logger.debug(
                f"Registered Element {element_name} with Domain as a {element_cls.element_type.value}"
            )

    @property
    def elements(self):
        elems = {}
        for name, element_type in properties().items():
            items = []
            for item in self._elements[element_type]:
                # Add only the class of the element
                items.append(self._elements[element_type][item].cls)

            if items:  # Only add element type if there are elements of that type
                elems[name] = items

        return elems

    def __repr__(self):
        return f"<DomainRegistry: {self._elements}>"


# Set up access to all elements as properties
for name, element_type in properties().items():
    """Set up element types as properties on Registry for easy access.

    Why? Since all elements are stored within a Dict in the registry, accessing
    them will mean knowing the storage structure. It is instead preferable to
    expose the elements by their element types as properties.
    """

    # This weird syntax is because when using lambdas in a for loop, we need to supply
    #   element_type as an argument with a default value of element_type
    prop = property(
        lambda self, element_type=element_type: self._elements[element_type]
    )  # pragma: no cover  # FIXME Is it possible to cover this line in tests

    # Set the property on the class
    setattr(_DomainRegistry, name, prop)
