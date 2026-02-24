"""Projection Functionality and Classes"""

import logging
import threading
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
from protean.utils.reflection import _FIELDS, _ID_FIELD_NAME, value_object_fields

logger = logging.getLogger(__name__)

# Thread-local stack used to pass init context (shadow kwargs) from
# __init__ to model_post_init across the Pydantic super().__init__() boundary.
# Pydantic clears __dict__ during validation, so we cannot stash data on the
# instance directly.
_projection_init_context: threading.local = threading.local()


# ---------------------------------------------------------------------------
# BaseProjection
# ---------------------------------------------------------------------------
class BaseProjection(BaseModel, OptionsMixin):
    """Base class for projections -- read-optimized, denormalized views
    maintained by projectors in response to domain events.

    Projections are mutable with identity-based equality. They support
    basic field types (``String``, ``Integer``, ``Float``, ``Identifier``,
    ``DateTime``, etc.) and ``ValueObject`` fields. ``Reference``,
    ``HasOne``, and ``HasMany`` fields are not allowed. Every projection
    must have at least one field marked with ``identifier=True``.

    ValueObject fields are stored as flattened shadow fields for persistence
    (e.g. ``billing_address_street``, ``billing_address_city``) and are
    queryable by individual attribute.

    Projections can be backed by a database provider or a cache (e.g. Redis).
    When ``cache`` is specified, it overrides the database ``provider``.

    Fields are declared using standard Python type annotations with optional
    ``Field`` constraints.

    **Meta Options**

    | Option | Type | Description |
    |--------|------|-------------|
    | ``provider`` | ``str`` | The persistence provider name (default: ``"default"``). |
    | ``cache`` | ``str`` | Cache adapter name. When set, overrides ``provider``. |
    | ``schema_name`` | ``str`` | The storage table/collection name. |
    | ``order_by`` | ``tuple`` | Default ordering for queries. |
    | ``limit`` | ``int`` | Default query result limit (default: ``100``). |

    Example::

        @domain.projection
        class OrderSummary(BaseProjection):
            order_id = Identifier(identifier=True)
            customer_name = String(max_length=100)
            total_amount = Float()
            status = String(max_length=20)
            shipping_address = ValueObject(Address)
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

        # Migrate annotation-style ValueObject descriptors to the class namespace.
        # Python puts ``field: ValueObject(Email)`` values into __annotations__
        # (not vars(cls)).  Pydantic and __pydantic_init_subclass__ scan vars(cls)
        # for descriptors, so they must live there.  We also explicitly trigger
        # __set_name__ because setattr does NOT invoke it.
        own_annots = getattr(cls, "__annotations__", {})
        to_remove: list[str] = []
        for name, value in list(own_annots.items()):
            if isinstance(value, ValueObject):
                setattr(cls, name, value)
                value.__set_name__(cls, name)
                to_remove.append(name)
        if to_remove:
            annots = dict(own_annots)
            for name in to_remove:
                del annots[name]
            cls.__annotations__ = annots

        resolve_fieldspecs(cls)

    @classmethod
    def __validate_for_basic_field_types(cls) -> None:
        """Reject Reference and Association descriptors.

        ValueObject descriptors are allowed — they are handled via shadow
        fields for flat persistence storage.
        """
        for field_name, field_obj in vars(cls).items():
            if isinstance(field_obj, (Reference, Association)):
                raise IncorrectUsageError(
                    f"Projections can only contain basic field types and ValueObjects. "
                    f"Remove {field_name} ({field_obj.__class__.__name__}) from class {cls.__name__}"
                )

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Called by Pydantic AFTER model_fields are fully populated."""
        super().__pydantic_init_subclass__(**kwargs)

        # Build __container_fields__ bridge from Pydantic model_fields
        fields_dict: dict[str, ResolvedField | ValueObject] = {}
        for fname, finfo in cls.model_fields.items():
            fields_dict[fname] = ResolvedField(fname, finfo, finfo.annotation)

        # Add ValueObject descriptors from the full MRO so that
        # reflection utilities (attributes, value_object_fields, etc.) work.
        for klass in cls.__mro__:
            for name, attr in vars(klass).items():
                if isinstance(attr, ValueObject) and name not in fields_dict:
                    fields_dict[name] = attr

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

    @staticmethod
    def _is_vo_descriptor(klass: type, name: str) -> bool:
        """Check if *name* is a ValueObject descriptor on *klass*'s MRO."""
        for mro_cls in klass.__mro__:
            if name in vars(mro_cls) and isinstance(vars(mro_cls)[name], ValueObject):
                return True
        return False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Check abstract before Pydantic validation to give a clear error
        # (abstract classes may lack fields, causing misleading Pydantic errors)
        if self.meta_.abstract is True:
            raise NotSupportedError(
                f"{self.__class__.__name__} class has been marked abstract"
                f" and cannot be instantiated"
            )

        # Pop VO descriptor kwargs and shadow field kwargs before Pydantic init.
        # Shadow fields (e.g. address_street, address_city) are dynamically
        # generated and must not reach Pydantic's __init__ (extra="forbid").
        descriptor_kwargs: dict[str, Any] = {}
        shadow_kwargs: dict[str, Any] = {}

        # Build the set of known shadow field names from VO descriptors
        _shadow_field_names: set[str] = set()
        for _, fobj in getattr(type(self), _FIELDS, {}).items():
            if isinstance(fobj, ValueObject):
                for sf in fobj.embedded_fields.values():
                    _shadow_field_names.add(sf.attribute_name)

        for name in list(kwargs):
            if name in _shadow_field_names:
                shadow_kwargs[name] = kwargs.pop(name)
            elif self._is_vo_descriptor(type(self), name):
                descriptor_kwargs[name] = kwargs.pop(name)

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
                # Also separate descriptor and shadow kwargs from template dicts
                for tname in list(template):
                    if tname in _shadow_field_names:
                        shadow_kwargs[tname] = template.pop(tname)
                    elif self._is_vo_descriptor(type(self), tname):
                        descriptor_kwargs[tname] = template.pop(tname)
                merged.update(template)
            merged.update(kwargs)
            kwargs = merged

        # Push context onto thread-local stack for model_post_init to retrieve.
        # Pydantic clears __dict__ during super().__init__(), so we cannot
        # stash data on the instance.
        stack: list[dict[str, Any]] = getattr(_projection_init_context, "stack", [])
        stack.append(
            {
                "descriptor_kwargs": descriptor_kwargs,
                "shadow_kwargs": shadow_kwargs,
            }
        )
        _projection_init_context.stack = stack

        try:
            super().__init__(**kwargs)
        except PydanticValidationError as e:
            raise ValidationError(convert_pydantic_errors(e))

    def model_post_init(self, __context: Any) -> None:
        # Pop init context from the thread-local stack (pushed by __init__)
        stack: list[dict[str, Any]] = getattr(_projection_init_context, "stack", [])
        if stack:
            ctx = stack.pop()
            descriptor_kwargs: dict[str, Any] = ctx["descriptor_kwargs"]
            shadow_kwargs: dict[str, Any] = ctx["shadow_kwargs"]
        else:
            descriptor_kwargs = {}
            shadow_kwargs = {}

        # Restore shadow field values directly into __dict__ (they bypass Pydantic)
        for name, value in shadow_kwargs.items():
            self.__dict__[name] = value  # type: ignore[reportIndexIssue]

        # Reconstruct ValueObjects from shadow kwargs when the VO itself
        # was not explicitly provided (e.g. during repository retrieval).
        for field_name, field_obj in value_object_fields(self).items():
            if field_name not in descriptor_kwargs and not getattr(
                self, field_name, None
            ):
                vo_kwargs: dict[str, Any] = {}
                for embedded_field in field_obj.embedded_fields.values():
                    vo_kwargs[embedded_field.field_name] = shadow_kwargs.get(
                        embedded_field.attribute_name
                    )
                # Only reconstruct if at least one value is not None
                if any(v is not None for v in vo_kwargs.values()):
                    descriptor_kwargs[field_name] = field_obj.value_object_cls(
                        **vo_kwargs
                    )

        # Set VO values via descriptors (triggers __set__ which populates
        # shadow fields and the VO instance in __dict__).
        for name, value in descriptor_kwargs.items():
            object.__setattr__(self, name, value)

        # Initialize VO shadow fields to None when the VO itself is not set
        for field_obj in value_object_fields(self).values():
            for _, shadow_field in field_obj.get_shadow_fields():
                attr_name = shadow_field.attribute_name
                if attr_name not in self.__dict__:
                    self.__dict__[attr_name] = None  # type: ignore[reportIndexIssue]

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
        elif getattr(self, "_initialized", False) and self._is_vo_descriptor(
            type(self), name
        ):
            # ValueObject descriptor: use object.__setattr__ to trigger
            # the descriptor protocol directly (bypassing Pydantic).
            object.__setattr__(self, name, value)
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

        ValueObject fields are serialized via the descriptor's
        ``as_dict()`` method.
        """
        result: dict[str, Any] = {}
        for fname, shim in getattr(self, _FIELDS, {}).items():
            value = getattr(self, fname, None)
            result[fname] = shim.as_dict(value)
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
