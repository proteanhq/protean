"""View Functionality and Classes"""
import logging

from protean.core.field.association import Association, Reference
from protean.core.field.base import Field
from protean.core.field.embedded import ValueObject
from protean.exceptions import (
    IncorrectUsageError,
    NotSupportedError,
)
from protean.utils import (
    DomainObjects,
    derive_element_class,
    inflection,
)
from protean.utils.container import BaseContainer

logger = logging.getLogger("protean.domain.view")


class BaseView(BaseContainer):
    element_type = DomainObjects.VIEW

    @classmethod
    def _default_options(cls):
        return [
            ("provider", "default"),
            ("cache", None),
            ("model", None),
            ("schema_name", inflection.underscore(cls.__name__)),
            ("order_by", ()),
        ]

    def __init_subclass__(subclass) -> None:
        super().__init_subclass__()

        if not subclass.meta_.abstract:
            subclass.__validate_id_field()

        subclass.__validate_for_basic_field_types()

    @classmethod
    def __validate_id_field(subclass):
        """Lookup the id field for this view and assign"""
        # FIXME What does it mean when there are no declared fields?
        #   Does it translate to an abstract view?
        if subclass.meta_.declared_fields:
            try:
                subclass.meta_.id_field = next(
                    field
                    for _, field in subclass.meta_.declared_fields.items()
                    if isinstance(field, (Field)) and field.identifier
                )
            except StopIteration:
                raise IncorrectUsageError(
                    {
                        "_entity": [
                            f"View `{subclass.__name__}` needs to have at least one identifier"
                        ]
                    }
                )

    @classmethod
    def __validate_for_basic_field_types(subclass):
        for field_name, field_obj in subclass.meta_.declared_fields.items():
            if isinstance(field_obj, (Reference, Association, ValueObject)):
                raise IncorrectUsageError(
                    {
                        "_entity": [
                            f"Views can only contain basic field types. "
                            f"Remove {field_name} ({field_obj.__class__.__name__}) from class {subclass.__name__}"
                        ]
                    }
                )

    def __eq__(self, other):
        """Equivalence check to be based only on Identity"""

        # FIXME Enhanced Equality Checks
        #   * Ensure IDs have values and both of them are not null
        #   * Ensure that the ID is of the right type
        #   * Ensure that Objects belong to the same `type`
        #   * Check Reference equality

        # FIXME Check if `==` and `in` operator work with __eq__

        if type(other) is type(self):
            self_id = getattr(self, self.meta_.id_field.field_name)
            other_id = getattr(other, other.meta_.id_field.field_name)

            return self_id == other_id

        return False

    def __hash__(self):
        """Overrides the default implementation and bases hashing on identity"""

        # FIXME Add Object Class Type to hash
        return hash(getattr(self, self.meta_.id_field.field_name))


def view_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseView, **kwargs)

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
    element_cls.meta_.cache = (
        kwargs.pop("cache", None)
        or (hasattr(element_cls, "meta_") and element_cls.meta_.cache)
        or None
    )
    element_cls.meta_.model = (
        kwargs.pop("model", None)
        or (hasattr(element_cls, "meta_") and element_cls.meta_.model)
        or None
    )

    if element_cls.meta_.provider and element_cls.meta_.cache:
        raise NotSupportedError(
            f"{element_cls.__name__} view can be persisted in"
            f"either a database or a cache, but not both"
        )

    return element_cls
