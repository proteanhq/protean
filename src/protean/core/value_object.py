"""Value Object Functionality and Classes"""

import logging
from collections import defaultdict
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

from protean.exceptions import (
    IncorrectUsageError,
    NotSupportedError,
    ValidationError,
)
from protean.fields.association import HasMany, HasOne, Reference
from protean.fields.embedded import ValueObject as ValueObjectField
from protean.fields.resolved import ResolvedField, convert_pydantic_errors
from protean.fields.spec import FieldSpec
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import OptionsMixin
from protean.utils.reflection import _FIELDS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BaseValueObject
# ---------------------------------------------------------------------------
class BaseValueObject(BaseModel, OptionsMixin):
    """Base class for Value Objects - immutable, no identity, equality by value.

    Fields are declared using standard Python type annotations with optional
    Field constraints.
    """

    element_type: ClassVar[str] = DomainObjects.VALUE_OBJECT

    model_config = ConfigDict(
        extra="forbid",
        ignored_types=(
            FieldSpec,
            ValueObjectField,
            HasOne,
            HasMany,
            Reference,
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

    def __new__(cls, *args: Any, **kwargs: Any) -> "BaseValueObject":
        if cls is BaseValueObject:
            raise NotSupportedError("BaseValueObject cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls) -> list[tuple[str, Any]]:
        return [
            ("abstract", False),
            ("part_of", None),
        ]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        # Initialize invariant storage (model_fields is NOT yet populated here)
        setattr(cls, "_invariants", defaultdict(dict))
        # Set empty __container_fields__ as placeholder
        setattr(cls, _FIELDS, {})

        # Resolve FieldSpec declarations before Pydantic processes annotations
        cls._resolve_fieldspecs()

    @classmethod
    def _resolve_fieldspecs(cls) -> None:
        from typing import Annotated, Optional

        from pydantic import Field as PydanticField

        from protean.fields.embedded import ValueObject as ValueObjectDescriptor
        from protean.fields.spec import FieldSpec, resolve_fieldspecs

        # Validate VO constraints BEFORE resolving FieldSpecs
        # Check both vars(cls) (assignment style) and __annotations__ (annotation style)
        def _validate_fieldspec(name: str, value: FieldSpec) -> None:
            if value.unique:
                raise IncorrectUsageError(
                    f"Value Objects cannot contain fields marked 'unique' "
                    f"(field '{name}')"
                )
            if value.identifier:
                raise IncorrectUsageError(
                    f"Value Objects cannot contain fields marked 'identifier' "
                    f"(field '{name}')"
                )

        for name, value in list(vars(cls).items()):
            if isinstance(value, FieldSpec):
                _validate_fieldspec(name, value)
            elif isinstance(value, (HasOne, HasMany, Reference)):
                raise IncorrectUsageError(
                    f"Value Objects cannot have associations. "
                    f"Remove {name} ({type(value).__name__}) from class {cls.__name__}"
                )

        # Also check annotation-style FieldSpecs
        for name, value in getattr(cls, "__annotations__", {}).items():
            if isinstance(value, FieldSpec):
                _validate_fieldspec(name, value)

        # Handle ValueObject() descriptors — convert to Pydantic annotations
        own_annots = getattr(cls, "__annotations__", {})
        processed: set[str] = set()

        # 1. Assignment style: descriptor in vars(cls)
        for name, value in list(vars(cls).items()):
            if isinstance(value, ValueObjectDescriptor):
                vo_cls = value.value_object_cls
                # Remove the descriptor from the class namespace
                try:
                    delattr(cls, name)
                except AttributeError:
                    pass
                # Add as a typed Pydantic annotation (optional by default)
                required = getattr(value, "required", False)
                if required:
                    own_annots[name] = vo_cls
                else:
                    pf = PydanticField(default=None)
                    own_annots[name] = Annotated[Optional[vo_cls], pf]
                processed.add(name)

        # 2. Annotation style: descriptor in __annotations__
        for name, value in list(own_annots.items()):
            if name not in processed and isinstance(value, ValueObjectDescriptor):
                vo_cls = value.value_object_cls
                required = getattr(value, "required", False)
                if required:
                    own_annots[name] = vo_cls
                else:
                    pf = PydanticField(default=None)
                    own_annots[name] = Annotated[Optional[vo_cls], pf]

        cls.__annotations__ = own_annots

        resolve_fieldspecs(cls)

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
        # Support template dict pattern: VO({"key": "val"}, key2="val2")
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

    def model_post_init(self, __context: Any) -> None:
        if self.meta_.abstract is True:
            raise NotSupportedError(
                f"{self.__class__.__name__} class has been marked abstract"
                f" and cannot be instantiated"
            )

        # Discover invariants from MRO (supports VOs used without domain registration)
        self._discover_invariants()

        self.defaults()

        errors = self._run_invariants("post")
        if errors:
            raise ValidationError(errors)

        object.__setattr__(self, "_initialized", True)

    def _discover_invariants(self) -> None:
        """Scan class MRO for @invariant decorated methods and register them."""
        for klass in type(self).__mro__:
            for name, attr in vars(klass).items():
                if callable(attr) and hasattr(attr, "_invariant"):
                    self._invariants[attr._invariant][name] = attr

    def __setattr__(self, name: str, value: Any) -> None:
        if not getattr(self, "_initialized", False):
            super().__setattr__(name, value)
        else:
            raise IncorrectUsageError(
                "Value Objects are immutable and cannot be modified once created"
            )

    def defaults(self) -> None:
        """Placeholder for defaults. Override in subclass when
        an attribute's default depends on other attribute values."""

    def _run_invariants(self, stage: str) -> dict[str, list[str]]:
        """Run invariants for a given stage. Return errors dict or empty."""
        errors: dict[str, list[str]] = defaultdict(list)

        for invariant_method in self._invariants.get(stage, {}).values():
            try:
                invariant_method(self)
            except ValidationError as err:
                for field_name in err.messages:
                    errors[field_name].extend(err.messages[field_name])

        return dict(errors) if errors else {}

    def _postcheck(self) -> dict[str, list[str]]:
        """Invariant checks performed after initialization.

        Returns a dict of errors (possibly empty) for compatibility with
        entity invariant runner (entity.py _run_invariants).
        """
        return self._run_invariants("post")

    def to_dict(self) -> dict[str, Any]:
        """Return data as a dictionary."""
        result: dict[str, Any] = {}
        for fname, shim in getattr(self, _FIELDS, {}).items():
            result[fname] = shim.as_dict(getattr(self, fname, None))
        return result

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return False
        return self.to_dict() == other.to_dict()

    def __hash__(self) -> int:
        return hash(frozenset(self.to_dict().items()))

    def __repr__(self) -> str:
        return "<%s: %s>" % (self.__class__.__name__, self)

    def __str__(self) -> str:
        return "%s object (%s)" % (
            self.__class__.__name__,
            "{}".format(self.to_dict()),
        )

    def __bool__(self) -> bool:
        return any(
            bool(getattr(self, field_name, None))
            for field_name in getattr(self, _FIELDS, {})
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def value_object_factory(element_cls: type, domain: Any, **opts: Any) -> type:
    # Always route to Pydantic base
    base_cls = BaseValueObject

    element_cls = derive_element_class(element_cls, base_cls, **opts)

    # Discover invariant methods using MRO scan (avoids inspect.getmembers deprecation warnings)
    for klass in element_cls.__mro__:
        for method_name, method in vars(klass).items():
            if (
                not (method_name.startswith("__") and method_name.endswith("__"))
                and callable(method)
                and hasattr(method, "_invariant")
            ):
                element_cls._invariants[method._invariant][method_name] = method

    return element_cls
