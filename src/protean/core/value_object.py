"""Value Object Functionality and Classes"""
import logging

from protean.core.field.association import Association, Reference
from protean.core.field.embedded import ValueObject
from protean.exceptions import IncorrectUsageError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import BaseContainer, OptionsMixin, fields

logger = logging.getLogger("protean.domain.value_object")


class BaseValueObject(BaseContainer, OptionsMixin):
    element_type = DomainObjects.VALUE_OBJECT

    class Meta:
        abstract = True

    def __init_subclass__(subclass) -> None:
        super().__init_subclass__()

        subclass.__validate_for_basic_field_types()

    @classmethod
    def __validate_for_basic_field_types(subclass):
        for field_name, field_obj in fields(subclass).items():
            if isinstance(field_obj, (Reference, Association, ValueObject)):
                raise IncorrectUsageError(
                    {
                        "_entity": [
                            f"Views can only contain basic field types. "
                            f"Remove {field_name} ({field_obj.__class__.__name__}) from class {subclass.__name__}"
                        ]
                    }
                )


def value_object_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseValueObject, **kwargs)

    return element_cls
