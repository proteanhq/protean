"""Projection Functionality and Classes"""

import inspect
import logging
import threading
from collections.abc import Mapping
from typing import Any, ClassVar, Self, TypeVar, cast

from pydantic import BaseModel, ConfigDict, PrivateAttr
from pydantic import ValidationError as PydanticValidationError

from protean.core.entity import (
    _add_missing_required_errors,
    _EntityState,
    _init_value_object_shadows,
    _pop_init_context,
    _rebuild_value_objects,
    _set_descriptor_values,
    _split_init_values,
    _value_object_shadow_names,
    _write_shadow_values,
)
from protean.exceptions import (
    IncorrectUsageError,
    InvalidOperationError,
    NotSupportedError,
    ValidationError,
)
from protean.fields import HasMany, HasOne, Reference, ValueObject
from protean.fields.association import Association
from protean.fields.resolved import ResolvedField, convert_pydantic_errors
from protean.fields.spec import FieldSpec, resolve_fieldspecs
from protean.utils import (
    DomainObjects,
    _derive_element_class,
    inflection,
)
from protean.utils.container import DerivedDefault, Element, OptionsMixin
from protean.utils.reflection import _FIELDS, _ID_FIELD_NAME

logger = logging.getLogger(__name__)

# Thread-local stack used to pass init context (shadow kwargs) from
# __init__ to model_post_init across the Pydantic super().__init__() boundary.
# Pydantic clears __dict__ during validation, so we cannot stash data on the
# instance directly.
_projection_init_context: threading.local = threading.local()


def _vo_shadow_field_names(projection_cls: type[Any]) -> set[str]:
    """Return the shadow field names of the projection's ``ValueObject`` fields.

    Only these names are taken out of the ``__init__`` values, so a truly
    unknown keyword still reaches Pydantic, which rejects it.
    """
    names: set[str] = set()
    for fobj in getattr(projection_cls, _FIELDS, {}).values():
        if isinstance(fobj, ValueObject):
            names |= _value_object_shadow_names(fobj)
    return names


# ---------------------------------------------------------------------------
# BaseProjection
# ---------------------------------------------------------------------------
class BaseProjection(Element, BaseModel, OptionsMixin):
    """Base class for projections: read-optimized views that projectors keep
    up to date from domain events.

    Projections are mutable, and two projections are equal when their
    identifiers are equal. They accept basic field types and ``ValueObject``
    fields. ``Reference``, ``HasOne`` and ``HasMany`` fields are not allowed.
    Every projection must have at least one field marked ``identifier=True``.
    Each attribute of a ``ValueObject`` field can be queried on its own. See
    the Projections guide for storage and querying.

    **Meta Options**

    | Option | Type | Description |
    |--------|------|-------------|
    | ``database`` | ``str`` | The ``[databases.*]`` entry that persists it (default: ``"default"``). |
    | ``cache`` | ``str`` | Cache adapter name. When set, overrides ``database``. |
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

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        if cls is BaseProjection:
            raise NotSupportedError("BaseProjection cannot be instantiated")
        return super().__new__(cls)

    _default_options: ClassVar[list[tuple[str, Any]]] = [
        ("abstract", False),
        ("cache", None),
        # When True, the projection is populated by a subscriber or event
        # handler (the anti-corruption-layer / cross-domain pattern) rather
        # than a co-located @projector. Suppresses PROJECTION_WITHOUT_PROJECTOR.
        ("externally_populated", False),
        ("indexes", ()),
        ("order_by", ()),
        ("database", "default"),
        (
            "schema_name",
            DerivedDefault(lambda cls: inflection.underscore(cls.__name__)),
        ),
        ("limit", 100),
        ("suppress_checks", ()),
    ]

    _renamed_options: ClassVar[Mapping[str, str]] = {"provider": "database"}

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
        # Migrate annotation-style ValueObject descriptors to the class namespace.
        # Python puts ``field: ValueObject(Email)`` values into __annotations__
        # (not vars(cls)).  Pydantic and __pydantic_init_subclass__ scan vars(cls)
        # for descriptors, so they must live there.  We also explicitly trigger
        # __set_name__ because setattr does NOT invoke it.
        #
        # In the typed-annotation style (``total: Money | None =
        # ValueObject(Money)``) the descriptor is already in vars(cls), but the
        # type annotation stays behind. Pydantic would then build a plain model
        # field from it that shadows the descriptor, so drop it here too.
        own_annots = inspect.get_annotations(cls)
        namespace = vars(cls)
        to_remove: list[str] = []
        for name, value in list(own_annots.items()):
            if isinstance(value, ValueObject):
                setattr(cls, name, value)
                value.__set_name__(cls, name)
                to_remove.append(name)
            elif isinstance(namespace.get(name), ValueObject):
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

        ValueObject descriptors are allowed; they are handled via shadow
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
        id_fld = next(
            (
                field
                for _, field in getattr(cls, _FIELDS, {}).items()
                if getattr(field, "identifier", False)
            ),
            None,
        )
        if id_fld is not None:
            setattr(cls, _ID_FIELD_NAME, id_fld.field_name)

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
        projection_cls = type(self)
        values = _split_init_values(
            args,
            kwargs,
            _vo_shadow_field_names(projection_cls),
            lambda name: self._is_vo_descriptor(projection_cls, name),
        )

        # Push context onto thread-local stack for model_post_init to retrieve.
        # Pydantic clears __dict__ during super().__init__(), so we cannot
        # stash data on the instance.
        stack: list[dict[str, Any]] = getattr(_projection_init_context, "stack", [])
        depth_before_init = len(stack)
        stack.append(
            {
                "descriptor_kwargs": values.descriptor_kwargs,
                "shadow_kwargs": values.shadow_kwargs,
            }
        )
        _projection_init_context.stack = stack

        # Collect validation errors (Pydantic + required value objects)
        # before raising.
        collected_errors: dict[str, list[str]] = {}

        try:
            super().__init__(**values.kwargs)
        except PydanticValidationError as e:
            collected_errors.update(convert_pydantic_errors(e))
        finally:
            # ``model_post_init`` pops this call's entry on a successful init.
            # When Pydantic validation raises before it runs, the entry is left
            # behind. Truncate to the pre-push depth so this call's entry is
            # balanced, without popping a parent's entry or double-popping one
            # ``model_post_init`` already removed.
            del stack[depth_before_init:]

        _add_missing_required_errors(
            projection_cls,
            values.descriptor_kwargs,
            values.shadow_kwargs,
            collected_errors,
        )

        if collected_errors:
            raise ValidationError(collected_errors)

    def model_post_init(self, context: Any, /) -> None:
        # Pop init context from the thread-local stack (pushed by __init__)
        ctx = _pop_init_context(_projection_init_context)
        descriptor_kwargs: dict[str, Any] = ctx["descriptor_kwargs"]
        shadow_kwargs: dict[str, Any] = ctx["shadow_kwargs"]

        _write_shadow_values(self, shadow_kwargs)
        _rebuild_value_objects(self, descriptor_kwargs, shadow_kwargs)

        _set_descriptor_values(self, descriptor_kwargs, shadow_kwargs)

        _init_value_object_shadows(self)

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
                raise ValidationError(convert_pydantic_errors(e)) from e

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

        return bool(getattr(self, id_field_name) == getattr(other, id_field_name))

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
        return f"<{self.__class__.__name__}: {self}>"

    def __str__(self) -> str:
        return "{} object ({})".format(
            self.__class__.__name__,
            f"{self.to_dict()}",
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
    element_cls = _derive_element_class(element_cls, base_cls, **opts)

    # ``_derive_element_class`` returns a ``BaseProjection`` subclass; narrow so
    # the projection-only surface (``meta_``) is visible to the type checker.
    projection_cls = cast(type[BaseProjection], element_cls)

    if not projection_cls.meta_.abstract and not hasattr(
        projection_cls, _ID_FIELD_NAME
    ):
        raise IncorrectUsageError(
            f"Projection `{projection_cls.__name__}` needs to have at least one identifier"
        )

    # If the projection has neither database nor cache provider, raise an error
    if not (projection_cls.meta_.database or projection_cls.meta_.cache):
        raise NotSupportedError(
            f"{projection_cls.__name__} projection needs to have either a database or a cache provider"
        )

    # A cache, when specified, overrides the provider
    if projection_cls.meta_.cache:
        projection_cls.meta_.database = None

    return element_cls
