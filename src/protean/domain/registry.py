import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

import inflection

from protean.exceptions import NotSupportedError
from protean.utils import DomainObjects, fully_qualified_name
from protean.utils.container import Element

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


@dataclass(slots=True)
class DomainRecord:
    """A record of a registered domain element.

    Attributes:
        name: The class name of the element
        qualname: The fully qualified name of the element
        class_type: The type of element (AGGREGATE, ENTITY, etc.)
        cls: The actual class object
        internal: Whether this element is internal to the platform
    """

    name: str
    qualname: str
    class_type: str
    cls: Any
    internal: bool = False

    def __repr__(self) -> str:
        return f"<class {self.name}: {self.qualname} ({self.class_type})>"


class _DomainRegistry:
    """Registry for domain elements with support for internal/platform elements.

    This registry maintains a catalog of all domain elements (aggregates, entities, etc.)
    and provides access to them through dynamically created properties. Elements marked
    as 'internal' are used by the platform itself and are not exposed through public
    property access.
    """

    __slots__ = ("_elements", "_elements_by_name")

    def __init__(self) -> None:
        self._elements: Dict[str, Dict[str, DomainRecord]] = {}
        self._elements_by_name: Dict[str, List[DomainRecord]] = {}

        # Initialize placeholders for element types
        for element_type in DomainObjects:
            self._elements[element_type.value] = {}

    def _reset(self) -> None:
        """Reset the registry, clearing all registered elements."""
        self._elements.clear()
        self._elements_by_name.clear()
        for element_type in DomainObjects:
            self._elements[element_type.value] = {}

    def _is_invalid_element_cls(self, element_cls: Element) -> bool:
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

    def register_element(self, element_cls: Element, internal: bool = False) -> None:
        """Register a domain element in the registry.

        Args:
            element_cls: The element class to register
            internal: Whether this is an internal platform element (not exposed publicly)

        Raises:
            NotSupportedError: If the element class is not valid
        """
        if self._is_invalid_element_cls(element_cls):
            raise NotSupportedError(
                f"Element `{element_cls.__name__}` is not a valid element class"
            )

        # Element name is always the fully qualified name of the class
        element_name = fully_qualified_name(element_cls)

        element_dict = self._elements[element_cls.element_type.value]
        if element_name in element_dict:
            logger.debug(f"Element {element_name} was already in the registry")
        else:
            element_record = DomainRecord(
                name=element_cls.__name__,
                qualname=element_name,
                class_type=element_cls.element_type.value,
                cls=element_cls,
                internal=internal,
            )

            element_dict[element_name] = element_record

            # Create an array to hold multiple elements of same name
            if element_cls.__name__ in self._elements_by_name:
                self._elements_by_name[element_cls.__name__].append(element_record)
            else:
                self._elements_by_name[element_cls.__name__] = [element_record]

            logger.debug(
                f"Registered Element {element_name} with Domain as a {element_cls.element_type.value}"
            )

    @property
    def elements(self) -> Dict[str, List[Any]]:
        """Return all registered elements grouped by type, excluding internal elements.

        Returns:
            Dictionary mapping element type names to lists of element classes
        """
        elems = {}
        for name, element_type in properties().items():
            items = []
            for record in self._elements[element_type].values():
                if not record.internal:
                    items.append(record.cls)

            if items:  # Only add element type if there are elements of that type
                elems[name] = items

        return elems

    def _public_elements(self, element_type: str) -> Dict[str, DomainRecord]:
        """Return a {qualname: DomainRecord} mapping **excluding** internal elements.

        Args:
            element_type: The type of elements to retrieve

        Returns:
            Dictionary mapping qualified names to DomainRecord instances
        """
        return {
            qname: record
            for qname, record in self._elements[element_type].items()
            if not record.internal
        }

    def __repr__(self) -> str:
        return f"<DomainRegistry: {self.elements}>"


def _create_element_property(element_type: str):
    """Factory function to create properties for element types."""

    def getter(self) -> Dict[str, DomainRecord]:
        return self._public_elements(element_type)

    return property(getter)


# Set up access to all elements as properties
for name, element_type in properties().items():
    """Set up element types as properties on Registry for easy access.

    Why? Since all elements are stored within a Dict in the registry, accessing
    them will mean knowing the storage structure. It is instead preferable to
    expose the elements by their element types as properties.
    """
    prop = _create_element_property(element_type)
    setattr(_DomainRegistry, name, prop)
