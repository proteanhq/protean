"""Query Functionality and Classes.

Queries are lightweight, immutable DTOs representing read intents against
projections -- the read-side counterpart of commands.
"""

import json
from collections import defaultdict
from typing import Any, ClassVar, Optional, TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

from protean.exceptions import (
    IncorrectUsageError,
    NotSupportedError,
    ValidationError,
)
from protean.fields.association import Association, Reference
from protean.fields.base import FieldBase
from protean.fields.embedded import ValueObject as ValueObjectField
from protean.fields.resolved import ResolvedField, convert_pydantic_errors
from protean.fields.spec import FieldSpec
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import OptionsMixin
from protean.utils.reflection import _FIELDS


# ---------------------------------------------------------------------------
# BaseQuery
# ---------------------------------------------------------------------------
class BaseQuery(BaseModel, OptionsMixin):
    """Base class for domain queries -- immutable DTOs representing a
    read intent against a projection.

    Queries are named with descriptive verbs (``GetOrdersByCustomer``,
    ``FindActiveUsers``, ``SearchProducts``) and processed by query handlers.
    They are immutable after construction and lighter than commands: no
    metadata, no stream, no event store concerns.

    Fields are declared using standard Python type annotations with optional
    ``Field`` constraints.

    **Meta Options**

    | Option | Type | Description |
    |--------|------|-------------|
    | ``part_of`` | ``type`` | The projection class this query targets. Required. |
    """

    element_type: ClassVar[str] = DomainObjects.QUERY

    model_config = ConfigDict(
        extra="forbid",
        ignored_types=(
            FieldSpec,
            FieldBase,
            str,
            int,
            float,
            bool,
            list,
            dict,
            tuple,
            set,
            type,
        ),
    )

    @classmethod
    def _default_options(cls) -> list[tuple[str, Any]]:
        return [
            ("abstract", False),
            ("part_of", None),
        ]

    def __new__(cls, *args: Any, **kwargs: Any) -> "BaseQuery":
        if cls is BaseQuery:
            raise NotSupportedError("BaseQuery cannot be instantiated")
        return super().__new__(cls)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        # Initialize invariant storage
        setattr(cls, "_invariants", defaultdict(dict))
        # Set empty __container_fields__ as placeholder
        setattr(cls, _FIELDS, {})

        # Convert ValueObject descriptors to direct type annotations
        # (queries don't need shadow fields — VOs serialize as nested dicts)
        cls._convert_vo_descriptors()

        # Resolve FieldSpec declarations before Pydantic processes annotations
        cls._resolve_fieldspecs()

        # Validate that only basic field types are used (no associations/references)
        cls.__validate_for_basic_field_types()

    @classmethod
    def _convert_vo_descriptors(cls) -> None:
        """Convert ValueObject descriptors to direct type annotations.

        Queries don't need shadow fields — VOs serialize as nested dicts.
        This converts ``email = ValueObject(Email)`` to the equivalent of
        ``email: Email | None = None``.
        """
        own_annots = getattr(cls, "__annotations__", {})
        names_to_remove: list[str] = []
        defaults_to_set: dict[str, None] = {}

        # 1. Assignment style: ``budget = ValueObject(Money)``
        for name, value in list(vars(cls).items()):
            if isinstance(value, ValueObjectField):
                vo_cls = value.value_object_cls
                if value.required:
                    own_annots[name] = vo_cls
                else:
                    own_annots[name] = Optional[vo_cls]
                    defaults_to_set[name] = None
                names_to_remove.append(name)

        # 2. Annotation style: ``budget: ValueObject(Money)``
        for name, annot_value in list(own_annots.items()):
            if isinstance(annot_value, ValueObjectField):
                vo_cls = annot_value.value_object_cls
                if annot_value.required:
                    own_annots[name] = vo_cls
                else:
                    own_annots[name] = Optional[vo_cls]
                    defaults_to_set[name] = None

        # Remove descriptors from namespace
        for name in names_to_remove:
            try:
                delattr(cls, name)
            except AttributeError:  # pragma: no cover
                pass  # Already removed by a parent __init_subclass__

        # Set defaults for optional VO fields
        for name, default in defaults_to_set.items():
            setattr(cls, name, default)

        cls.__annotations__ = own_annots

    @classmethod
    def _resolve_fieldspecs(cls) -> None:
        from protean.fields.spec import resolve_fieldspecs

        resolve_fieldspecs(cls)

    @classmethod
    def __validate_for_basic_field_types(cls) -> None:
        """Reject association/reference field descriptors in Queries."""
        for field_name, field_obj in vars(cls).items():
            if isinstance(field_obj, (Association, Reference)):
                raise IncorrectUsageError(
                    f"Queries can only contain basic field types. "
                    f"Remove {field_name} ({field_obj.__class__.__name__}) "
                    f"from class {cls.__name__}"
                )

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Called by Pydantic AFTER model_fields are fully populated."""
        super().__pydantic_init_subclass__(**kwargs)

        # Build __container_fields__ bridge from Pydantic model_fields
        fields_dict: dict[str, ResolvedField] = {}
        for fname, finfo in cls.model_fields.items():
            fields_dict[fname] = ResolvedField(fname, finfo, finfo.annotation)
        setattr(cls, _FIELDS, fields_dict)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Create a new query instance.

        Accepts keyword arguments matching the declared fields.  Optionally,
        a ``dict`` can be passed as a positional argument to serve as a
        template — keyword arguments take precedence over template values.

        Args:
            *args (dict): Optional template dictionaries for field values.
            **kwargs (Any): Field values for the query.

        Raises:
            ValidationError: If field validation fails.

        Example::

            # Keyword arguments
            GetOrdersByCustomer(customer_id="abc", status="pending")

            # Template dict pattern
            GetOrdersByCustomer({"customer_id": "abc"}, page=2)
        """
        # Support template dict pattern: Query({"key": "val"}, key2="val2")
        # Keyword args take precedence over template dict values.
        if args:
            merged: dict[str, Any] = {}
            for template in args:
                if not isinstance(template, dict):
                    raise AssertionError(
                        f"Positional argument {template} passed must be a dict. "
                        f"This argument serves as a template for loading common "
                        f"values.",
                    )
                merged.update(template)
            merged.update(kwargs)
            kwargs = merged

        try:
            super().__init__(**kwargs)
        except PydanticValidationError as e:
            raise ValidationError(convert_pydantic_errors(e))

        object.__setattr__(self, "_initialized", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if not getattr(self, "_initialized", False):
            super().__setattr__(
                name, value
            )  # pragma: no cover — Pydantic init uses object.__setattr__ directly
        else:
            raise IncorrectUsageError(
                "Query objects are immutable and cannot be modified once created"
            )

    @property
    def payload(self) -> dict[str, Any]:
        """Return the payload of the query."""
        return {
            fname: shim.as_dict(getattr(self, fname, None))
            for fname, shim in getattr(self, _FIELDS, {}).items()
        }

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return False
        return self.payload == other.payload

    def __hash__(self) -> int:
        return hash(json.dumps(self.payload, sort_keys=True))

    def to_dict(self) -> dict[str, Any]:
        """Return data as a dictionary."""
        return self.payload.copy()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
_T = TypeVar("_T")


def query_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
    base_cls = BaseQuery

    element_cls = derive_element_class(element_cls, base_cls, **opts)

    if not element_cls.meta_.part_of and not element_cls.meta_.abstract:
        raise IncorrectUsageError(
            f"Query `{element_cls.__name__}` needs to be associated with a projection"
        )

    return element_cls
