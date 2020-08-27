import logging

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict

from protean.utils import fully_qualified_name, DomainObjects

logger = logging.getLogger("protean.domain")


@dataclass
class _DomainRegistry:
    _elements: Dict[str, dict] = field(default_factory=dict)

    @dataclass
    class DomainRecord:
        name: str
        qualname: str
        class_type: str
        cls: Any

    def __post_init__(self):
        """Initialize placeholders for element types"""
        for element_type in DomainObjects:
            self._elements[element_type.value] = defaultdict(dict)

    def register_element(self, element_cls):
        if element_cls.element_type.name not in DomainObjects.__members__:
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

            logger.debug(
                f"Registered Element {element_name} with Domain as a {element_cls.element_type.value}"
            )

    def delist_element(self, element_cls):
        if element_cls.element_type.name not in DomainObjects.__members__:
            raise NotImplementedError

        element_name = fully_qualified_name(element_cls)

        self._elements[element_cls.element_type.value].pop(element_name, None)

    @property
    def aggregates(self):
        return self._elements[DomainObjects.AGGREGATE.value]

    @property
    def application_services(self):
        return self._elements[DomainObjects.APPLICATION_SERVICE.value]

    @property
    def commands(self):
        return self._elements[DomainObjects.COMMAND.value]

    @property
    def command_handlers(self):
        return self._elements[DomainObjects.COMMAND_HANDLER.value]

    @property
    def domain_events(self):
        return self._elements[DomainObjects.DOMAIN_EVENT.value]

    @property
    def domain_services(self):
        return self._elements[DomainObjects.DOMAIN_SERVICE.value]

    @property
    def emails(self):
        return self._elements[DomainObjects.EMAIL.value]

    @property
    def models(self):
        return self._elements[DomainObjects.MODEL.value]

    @property
    def entities(self):
        return self._elements[DomainObjects.ENTITY.value]

    @property
    def repositories(self):
        return self._elements[DomainObjects.REPOSITORY.value]

    @property
    def serializers(self):
        return self._elements[DomainObjects.SERIALIZER.value]

    @property
    def subscribers(self):
        return self._elements[DomainObjects.SUBSCRIBER.value]

    @property
    def value_objects(self):
        return self._elements[DomainObjects.VALUE_OBJECT.value]
