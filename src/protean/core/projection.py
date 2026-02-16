"""Projection Functionality and Classes"""

import logging
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel, ConfigDict, PrivateAttr
from pydantic import ValidationError as PydanticValidationError

from protean.core.entity import _EntityState
from protean.fields.resolved import ResolvedField, convert_pydantic_errors
from protean.exceptions import (
    IncorrectUsageError,
    InvalidOperationError,
    NotSupportedError,
    ValidationError,
)
from protean.fields import HasMany, HasOne, Reference, ValueObject
from protean.fields.association import Association
from protean.fields.spec import FieldSpec
from protean.utils import (
    DomainObjects,
    derive_element_class,
    inflection,
)
from protean.utils.container import OptionsMixin
from protean.utils.reflection import _FIELDS, _ID_FIELD_NAME

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BaseProjection
# ---------------------------------------------------------------------------
class BaseProjection(BaseModel, OptionsMixin):
    """Base class for Projection domain elements.

    Mutable, identity-based equality, with basic field types only.
    Uses ``validate_assignment=True`` for field declaration, validation,
    and mutation.

    Fields are declared using standard Python type annotations with optional
    ``Field`` constraints. Identity fields must be annotated with
    ``json_schema_extra={"identifier": True}``.
    """

    element_type: ClassVar[str] = DomainObjects.PROJECTION

    model_config = ConfigDict(
        validate_assignment=True,
        extra="forbid",
        ignored_types=(
            HasOne,
            HasMany,
            Reference,
            ValueObject,
            FieldSpec,
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

    # Internal state (PrivateAttr — excluded from model_dump/schema)
    _initialized: bool = PrivateAttr(default=False)
    _state: _EntityState = PrivateAttr(default_factory=_EntityState)

    def __new__(cls, *args: Any, **kwargs: Any) -> "BaseProjection":
        if cls is BaseProjection:
            raise NotSupportedError("BaseProjection cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls) -> list[tuple[str, Any]]:
        return [
            ("abstract", False),
            ("cache", None),
            ("database_model", None),
            ("order_by", ()),
            ("provider", "default"),
            ("schema_name", inflection.underscore(cls.__name__)),
            ("limit", 100),
        ]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Set empty __container_fields__ as placeholder
        setattr(cls, _FIELDS, {})

        # Resolve FieldSpec declarations before Pydantic processes annotations
        cls._resolve_fieldspecs()

        # Validate that only basic field types are used (no descriptors)
        cls.__validate_for_basic_field_types()

    @classmethod
    def _resolve_fieldspecs(cls) -> None:
        from protean.fields.spec import resolve_fieldspecs

        resolve_fieldspecs(cls)

    @classmethod
    def __validate_for_basic_field_types(cls) -> None:
        """Reject non-basic field descriptors (ValueObject, Reference, Association)."""
        for field_name, field_obj in vars(cls).items():
            if isinstance(field_obj, (Reference, Association, ValueObject)):
                raise IncorrectUsageError(
                    f"Projections can only contain basic field types. "
                    f"Remove {field_name} ({field_obj.__class__.__name__}) from class {cls.__name__}"
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

        # Track identity field
        if not cls.meta_.abstract:
            cls.__track_id_field()

    @classmethod
    def __track_id_field(cls) -> None:
        """Find the field marked ``identifier=True`` and record its name."""
        try:
            id_fld = next(
                field
                for _, field in getattr(cls, _FIELDS, {}).items()
                if getattr(field, "identifier", False)
            )
            setattr(cls, _ID_FIELD_NAME, id_fld.field_name)
        except StopIteration:
            pass

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Check abstract before Pydantic validation to give a clear error
        # (abstract classes may lack fields, causing misleading Pydantic errors)
        if self.meta_.abstract is True:
            raise NotSupportedError(
                f"{self.__class__.__name__} class has been marked abstract"
                f" and cannot be instantiated"
            )

        # Support template dict pattern: Projection({"key": "val"}, key2="val2")
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
        self.defaults()
        self._initialized = True

    def defaults(self) -> None:
        """Placeholder for defaults.

        Override in subclass when an attribute's default depends on other
        attribute values.
        """

    # ------------------------------------------------------------------
    # Mutation with Pydantic error conversion + state tracking
    # ------------------------------------------------------------------
    def __setattr__(self, name: str, value: Any) -> None:
        if name in self.__class__.model_fields and getattr(self, "_initialized", False):
            # Prevent mutation of identifier fields once set
            id_field_name = getattr(self.__class__, _ID_FIELD_NAME, None)
            if name == id_field_name:
                existing = getattr(self, name, None)
                if existing is not None and value != existing:
                    raise InvalidOperationError(
                        "Identifiers cannot be changed once set"
                    )

            try:
                super().__setattr__(name, value)
            except PydanticValidationError as e:
                raise ValidationError(convert_pydantic_errors(e))

            # Mark projection as changed so repository persists updates
            self._state.mark_changed()
        else:
            super().__setattr__(name, value)

    # ------------------------------------------------------------------
    # Identity-based equality
    # ------------------------------------------------------------------
    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return False

        id_field_name = getattr(self.__class__, _ID_FIELD_NAME, None)
        if id_field_name is None:
            return False

        return getattr(self, id_field_name) == getattr(other, id_field_name)

    def __hash__(self) -> int:
        id_field_name = getattr(self.__class__, _ID_FIELD_NAME, None)
        if id_field_name is None:
            return id(self)
        return hash(getattr(self, id_field_name))

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Return projection data as a dictionary.

        Internal fields (prefixed with ``_``) are excluded for consistency
        with the entity ``to_dict()`` behaviour.
        """
        result: dict[str, Any] = {}
        for fname, shim in getattr(self, _FIELDS, {}).items():
            if fname.startswith("_"):
                continue
            result[fname] = shim.as_dict(getattr(self, fname, None))
        return result

    @property
    def state_(self) -> _EntityState:
        """Access projection lifecycle state."""
        return self._state

    @state_.setter
    def state_(self, value: _EntityState) -> None:
        self._state = value

    def __repr__(self) -> str:
        return "<%s: %s>" % (self.__class__.__name__, self)

    def __str__(self) -> str:
        return "%s object (%s)" % (
            self.__class__.__name__,
            "{}".format(self.to_dict()),
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
_T = TypeVar("_T")


def projection_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
    """Factory method to create a projection class.

    This method is used to create a projection class. It is called during
    domain registration.
    """
    # If opts has a `limit` key and it is negative, set it to None
    if "limit" in opts and opts["limit"] is not None and opts["limit"] < 0:
        opts["limit"] = None

    # Always route to Pydantic base
    base_cls = BaseProjection

    # Derive the projection class from the base projection class
    element_cls = derive_element_class(element_cls, base_cls, **opts)

    if not element_cls.meta_.abstract and not hasattr(element_cls, _ID_FIELD_NAME):
        raise IncorrectUsageError(
            f"Projection `{element_cls.__name__}` needs to have at least one identifier"
        )

    # If the projection has neither database nor cache provider, raise an error
    if not (element_cls.meta_.provider or element_cls.meta_.cache):
        raise NotSupportedError(
            f"{element_cls.__name__} projection needs to have either a database or a cache provider"
        )

    # A cache, when specified, overrides the provider
    if element_cls.meta_.cache:
        element_cls.meta_.provider = None

    return element_cls
