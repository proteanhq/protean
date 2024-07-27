"""View Functionality and Classes"""

import logging

from protean.core.entity import _EntityState
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.fields import Field, Reference, ValueObject
from protean.fields.association import Association
from protean.utils import DomainObjects, derive_element_class, inflection
from protean.utils.container import BaseContainer, OptionsMixin
from protean.utils.reflection import _ID_FIELD_NAME, declared_fields, id_field

logger = logging.getLogger(__name__)


class BaseView(BaseContainer, OptionsMixin):
    element_type = DomainObjects.VIEW

    def __new__(cls, *args, **kwargs):
        if cls is BaseView:
            raise NotSupportedError("BaseView cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls):
        return [
            ("abstract", False),
            ("cache", None),
            ("model", None),
            ("order_by", ()),
            ("provider", "default"),
            ("schema_name", inflection.underscore(cls.__name__)),
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
        if declared_fields(subclass):
            try:
                id_field = next(
                    field
                    for _, field in declared_fields(subclass).items()
                    if isinstance(field, (Field)) and field.identifier
                )

                setattr(subclass, _ID_FIELD_NAME, id_field.field_name)

            except StopIteration:
                # View does not have an ID field. An error will be thrown
                #   on registering the view, in the factory method.
                pass

    @classmethod
    def __validate_for_basic_field_types(subclass):
        for field_name, field_obj in declared_fields(subclass).items():
            if isinstance(field_obj, (Reference, Association, ValueObject)):
                raise IncorrectUsageError(
                    f"Views can only contain basic field types. "
                    f"Remove {field_name} ({field_obj.__class__.__name__}) from class {subclass.__name__}"
                )

    def __init__(self, *template, **kwargs):
        super().__init__(*template, **kwargs)

        # Set up the storage for instance state
        self.state_ = _EntityState()

    def __eq__(self, other):
        """Equivalence check to be based only on Identity"""

        # FIXME Enhanced Equality Checks
        #   * Ensure IDs have values and both of them are not null
        #   * Ensure that the ID is of the right type
        #   * Ensure that Objects belong to the same `type`
        #   * Check Reference equality

        # FIXME Check if `==` and `in` operator work with __eq__

        if type(other) is type(self):
            self_id = getattr(self, id_field(self).field_name)
            other_id = getattr(other, id_field(other).field_name)

            return self_id == other_id

        return False

    def __hash__(self):
        """Overrides the default implementation and bases hashing on identity"""

        # FIXME Add Object Class Type to hash
        return hash(getattr(self, id_field(self).field_name))


def view_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseView, **opts)

    if not element_cls.meta_.abstract and not hasattr(element_cls, _ID_FIELD_NAME):
        raise IncorrectUsageError(
            f"View `{element_cls.__name__}` needs to have at least one identifier"
        )

    element_cls.meta_.provider = (
        opts.pop("provider", None)
        or (hasattr(element_cls, "meta_") and element_cls.meta_.provider)
        or "default"
    )
    element_cls.meta_.cache = (
        opts.pop("cache", None)
        or (hasattr(element_cls, "meta_") and element_cls.meta_.cache)
        or None
    )
    element_cls.meta_.model = (
        opts.pop("model", None)
        or (hasattr(element_cls, "meta_") and element_cls.meta_.model)
        or None
    )

    if element_cls.meta_.provider and element_cls.meta_.cache:
        raise NotSupportedError(
            f"{element_cls.__name__} view can be persisted in"
            f"either a database or a cache, but not both"
        )

    return element_cls
