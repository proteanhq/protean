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
    props = {}
    for element_type in DomainObjects:
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

            # ✅ New fields for type tracking
            self.own_fields: Dict[str, str] = {}
            self.base_fields: Dict[str, Dict[str, str]] = {}

        def __repr__(self):
            return f"<class {self.name}: {self.qualname} ({self.class_type})>"

    def __init__(self):
        self._elements: Dict[str, dict] = {}
        self._elements_by_name: Dict[str, list] = {}

        for element_type in DomainObjects:
            self._elements[element_type.value] = defaultdict(dict)

    def _reset(self):
        for element_type in DomainObjects:
            self._elements[element_type.value] = defaultdict(dict)
        self._elements_by_name: Dict[str, list] = {}

    def _is_invalid_element_cls(self, element_cls):
        return (
            not hasattr(element_cls, "element_type")
            or not isinstance(element_cls.element_type, Enum)
            or element_cls.element_type.name not in DomainObjects.__members__
        )

    def _extract_type_info(self, cls):
        """✅ Extract both own and inherited fields from valid domain element bases."""
        own_fields = getattr(cls, "__annotations__", {})

        base_fields = {}
        for base in cls.__bases__:
            if hasattr(base, "element_type"):
                base_name = fully_qualified_name(base)
                base_fields[base_name] = getattr(base, "__annotations__", {})

        return own_fields, base_fields

    def register_element(self, element_cls):
        if self._is_invalid_element_cls(element_cls):
            raise NotSupportedError(
                f"Element `{element_cls.__name__}` is not a valid element class"
            )

        element_name = fully_qualified_name(element_cls)
        element = self._elements[element_cls.element_type.value][element_name]

        if element:
            logger.debug(f"Element {element_name} was already in the registry")
        else:
            element_record = _DomainRegistry.DomainRecord(
                name=element_cls.__name__,
                qualname=element_name,
                class_type=element_cls.element_type.value,
                cls=element_cls,
            )

            # ✅ Set type info (own and inherited)
            own, inherited = self._extract_type_info(element_cls)
            element_record.own_fields = own
            element_record.base_fields = inherited

            self._elements[element_cls.element_type.value][element_name] = element_record

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
                items.append(self._elements[element_type][item].cls)
            if items:
                elems[name] = items
        return elems

    def __repr__(self):
        return f"<DomainRegistry: {self.elements}>"


# Set up access to all elements as properties
for name, element_type in properties().items():
    prop = property(
        lambda self, element_type=element_type: self._elements[element_type]
    )
    setattr(_DomainRegistry, name, prop)
