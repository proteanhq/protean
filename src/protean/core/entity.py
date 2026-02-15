"""Entity Functionality and Classes"""

from __future__ import annotations

import functools
import logging
import threading
from collections import defaultdict
from functools import partial
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, PrivateAttr
from pydantic import ValidationError as PydanticValidationError

from protean.fields.resolved import ResolvedField
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    InvalidOperationError,
    NotSupportedError,
    ValidationError,
)
from protean.fields import (
    HasMany,
    HasOne,
    Reference,
    ValueObject,
)
from protean.fields.basic import ValueObjectList
from protean.fields.spec import FieldSpec
from protean.fields.association import Association, _ReferenceField
from protean.fields.embedded import _ShadowField
from protean.utils import (
    DomainObjects,
    derive_element_class,
    generate_identity,
    inflection,
)
from protean.utils.container import OptionsMixin
from protean.utils.reflection import (
    _FIELDS,
    _ID_FIELD_NAME,
    association_fields,
    declared_fields,
    reference_fields,
    value_object_fields,
)

logger = logging.getLogger(__name__)

# Thread-local stack used to pass init context (descriptor kwargs, shadow
# kwargs, owner, root) from ``__init__`` to ``model_post_init`` across the
# Pydantic ``super().__init__()`` boundary.  Pydantic clears ``__dict__``
# during validation, so we cannot stash data on the instance directly.
_init_context: threading.local = threading.local()

# Descriptor types that should bypass Pydantic's __setattr__ and be routed
# through the Python descriptor protocol via object.__setattr__().
_DESCRIPTOR_TYPES = (
    Association,
    Reference,
    ValueObject,
    ValueObjectList,
    _ReferenceField,
    _ShadowField,
)


class _FieldsCacheDescriptor:
    def __get__(self, instance, cls=None):
        if instance is None:
            return self
        res = instance.fields_cache = {}
        return res


class _EntityState:
    """Store entity instance state."""

    def __init__(self):
        self._new = True
        self._changed = False
        self._destroyed = False

    @property
    def is_new(self):
        return self._new

    @property
    def is_persisted(self):
        return not self._new

    @property
    def is_changed(self):
        return self._changed

    @property
    def is_destroyed(self):
        return self._destroyed

    def mark_new(self):
        self._new = True

    def mark_saved(self):
        self._new = False
        self._changed = False

    mark_retrieved = (
        mark_saved  # Alias as placeholder so that future change wont affect interface
    )

    def mark_changed(self):
        if not (self._new or self._destroyed):
            self._changed = True

    def mark_destroyed(self):
        self._destroyed = True
        self._changed = False

    fields_cache = _FieldsCacheDescriptor()


# ---------------------------------------------------------------------------
# BaseEntity
# ---------------------------------------------------------------------------
class BaseEntity(BaseModel, OptionsMixin):
    """Base class for Entity domain elements.

    Mutable, identity-based equality, with invariant checking.
    Uses ``validate_assignment=True`` for field declaration, validation,
    and mutation.

    Fields are declared using standard Python type annotations with optional
    ``Field`` constraints.  Identity fields must be annotated with
    ``json_schema_extra={"identifier": True}``.
    """

    element_type: ClassVar[str] = DomainObjects.ENTITY

    model_config = ConfigDict(
        validate_assignment=True,
        extra="forbid",
        ignored_types=(
            HasOne,
            HasMany,
            Reference,
            ValueObject,
            ValueObjectList,
            FieldSpec,
            # Allow plain class constants (e.g. REGEXP = r"...") without
            # requiring ClassVar annotations — mirrors pre-Pydantic behavior.
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
    _root: Any = PrivateAttr(default=None)
    _owner: Any = PrivateAttr(default=None)
    _temp_cache: Any = PrivateAttr(
        default_factory=lambda: defaultdict(lambda: defaultdict(dict))
    )
    _events: list = PrivateAttr(default_factory=list)
    _disable_invariant_checks: bool = PrivateAttr(default=False)

    def __new__(cls, *args: Any, **kwargs: Any) -> BaseEntity:
        if cls is BaseEntity:
            raise NotSupportedError("BaseEntity cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls) -> list[tuple[str, Any]]:
        return [
            ("aggregate_cluster", None),
            ("auto_add_id_field", True),
            ("database_model", None),
            ("part_of", None),
            ("provider", "default"),
            ("schema_name", inflection.underscore(cls.__name__)),
            ("limit", 100),
        ]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        # Initialize invariant storage
        setattr(cls, "_invariants", defaultdict(dict))
        # Set empty __container_fields__ as placeholder (populated later by __pydantic_init_subclass__)
        setattr(cls, _FIELDS, {})

        # Resolve FieldSpec declarations BEFORE auto-id injection, so that
        # FieldSpec identifiers (e.g. ``id = Identifier()``) are visible
        # to ``_maybe_inject_auto_id()``.
        cls._resolve_fieldspecs()

        # Auto-inject `id` field for concrete aggregate/entity subclasses.
        # This runs BEFORE Pydantic's complete_model_class(), so the injected
        # annotation is picked up by Pydantic's model field processing.
        cls._maybe_inject_auto_id()

    @classmethod
    def _resolve_fieldspecs(cls) -> None:
        from protean.fields.spec import resolve_fieldspecs

        resolve_fieldspecs(cls)

    @classmethod
    def _maybe_inject_auto_id(cls) -> None:
        """Inject an ``id`` field if no identifier field is declared.

        Only fires for direct Pydantic BaseEntity/BaseAggregate subclasses.
        Skips:
        - The framework base classes themselves (BaseEntity, BaseAggregate).
        - Classes created by ``_prepare_pydantic_namespace`` (marked with
          ``__auto_id_handled__``), where id injection is already handled
          and respects the ``auto_add_id_field`` option.
        """
        from pydantic import Field as PydanticField
        from pydantic.fields import FieldInfo

        # Skip the framework base classes themselves
        if cls.__name__ in ("BaseEntity", "BaseAggregate"):
            return

        # Skip classes already processed by _prepare_pydantic_namespace
        if vars(cls).get("__auto_id_handled__"):
            return

        own_annots = vars(cls).get("__annotations__", {})

        # Check if any class-level FieldInfo already declares an identifier
        for value in vars(cls).values():
            if isinstance(value, FieldInfo):
                extra = value.json_schema_extra
                if isinstance(extra, dict) and extra.get("identifier"):
                    return

        # Check annotations for identifier (handles Annotated with lazy strings
        # from ``from __future__ import annotations``)
        for annot_value in own_annots.values():
            if isinstance(annot_value, str) and '"identifier": True' in annot_value:
                return
            if isinstance(annot_value, str) and "'identifier': True" in annot_value:
                return
            # Handle resolved Annotated types (no from __future__)
            if hasattr(annot_value, "__metadata__"):
                for meta in annot_value.__metadata__:
                    if isinstance(meta, FieldInfo):
                        extra = meta.json_schema_extra
                        if isinstance(extra, dict) and extra.get("identifier"):
                            return

        # Check inherited __container_fields__ for existing identifier
        for parent in cls.__mro__[1:]:
            for fobj in getattr(parent, _FIELDS, {}).values():
                if getattr(fobj, "identifier", False):
                    return

        # No identifier found — inject auto-id
        if "id" not in own_annots:
            from uuid import UUID

            annots = dict(own_annots)
            annots["id"] = str | int | UUID
            cls.__annotations__ = annots
            setattr(
                cls,
                "id",
                PydanticField(
                    default_factory=generate_identity,
                    json_schema_extra={"identifier": True},
                ),
            )

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Called by Pydantic AFTER model_fields are fully populated."""
        super().__pydantic_init_subclass__(**kwargs)

        # Build __container_fields__ bridge from Pydantic model_fields
        fields_dict: dict[str, Any] = {}
        for fname, finfo in cls.model_fields.items():
            fields_dict[fname] = ResolvedField(fname, finfo, finfo.annotation)

        # Add association and VO descriptors from the full MRO
        for klass in cls.__mro__:
            for name, attr in vars(klass).items():
                if (
                    isinstance(
                        attr, (Association, Reference, ValueObject, ValueObjectList)
                    )
                    and name not in fields_dict
                ):
                    fields_dict[name] = attr

        setattr(cls, _FIELDS, fields_dict)

        # Track identity field
        if not cls.meta_.abstract:
            cls.__track_id_field()

    @classmethod
    def __track_id_field(cls) -> None:
        """Find the field marked ``identifier=True`` and record its name."""
        id_fields = [
            field
            for _, field in getattr(cls, _FIELDS, {}).items()
            if getattr(field, "identifier", False)
        ]

        if len(id_fields) > 1:
            raise NotSupportedError(
                {
                    "_entity": [
                        f"Multiple identifier fields found in entity {cls.__name__}. "
                        "Only one identifier field is allowed."
                    ]
                }
            )
        elif len(id_fields) == 1:
            setattr(cls, _ID_FIELD_NAME, id_fields[0].field_name)

    @staticmethod
    def _get_class_descriptor(cls: type, name: str) -> Any:
        """Look up a descriptor on the class MRO without triggering __get__.

        ``getattr(cls, name)`` invokes the data descriptor protocol, which
        may return ``None`` or ``[]`` for association descriptors.  Scanning
        ``__dict__`` directly returns the raw descriptor object.
        """
        for klass in cls.__mro__:
            if name in vars(klass):
                attr = vars(klass)[name]
                if isinstance(attr, _DESCRIPTOR_TYPES):
                    return attr
        return None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Pop internal kwargs that should not reach Pydantic
        owner = kwargs.pop("_owner", None)
        root = kwargs.pop("_root", None)
        # _version is a PrivateAttr; accept it in kwargs for backward
        # compatibility (e.g. repository hydration) but set it after init.
        _version_value = kwargs.pop("_version", None)

        # Pop association/VO descriptor kwargs and shadow field kwargs before
        # Pydantic init.  Shadow fields (e.g. order_id, billing_address_street)
        # are set dynamically during domain resolution and must not be passed
        # to Pydantic's __init__ which rejects them with extra="forbid".
        descriptor_kwargs: dict[str, Any] = {}
        shadow_kwargs: dict[str, Any] = {}

        # Build the set of known shadow field names from descriptors in
        # __container_fields__.  This prevents silently swallowing truly
        # unknown kwargs that Pydantic should reject.
        _shadow_field_names: set[str] = set()
        for _, fobj in getattr(type(self), _FIELDS, {}).items():
            if isinstance(fobj, Reference):
                attr_name = fobj.get_attribute_name()
                if attr_name:
                    _shadow_field_names.add(attr_name)
            elif isinstance(fobj, ValueObject):
                for sf in fobj.embedded_fields.values():
                    _shadow_field_names.add(sf.attribute_name)

        for name in list(kwargs):
            if self._get_class_descriptor(type(self), name) is not None:
                descriptor_kwargs[name] = kwargs.pop(name)
            elif name in _shadow_field_names:
                shadow_kwargs[name] = kwargs.pop(name)

        # Support template dict pattern: Entity({"key": "val"}, key2="val2")
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
                    if self._get_class_descriptor(type(self), tname) is not None:
                        descriptor_kwargs[tname] = template.pop(tname)
                    elif tname in _shadow_field_names:
                        shadow_kwargs[tname] = template.pop(tname)
                merged.update(template)
            merged.update(kwargs)
            kwargs = merged

        # Collect all validation errors (Pydantic + required descriptors) before raising
        collected_errors: dict[str, list[str]] = {}

        # Push init context onto the thread-local stack so that
        # model_post_init (called by Pydantic inside super().__init__())
        # can retrieve descriptor/shadow kwargs.  Pydantic wipes __dict__
        # during validation, so we cannot stash data on the instance.
        stack: list[dict[str, Any]] = getattr(_init_context, "stack", [])
        stack.append(
            {
                "descriptor_kwargs": descriptor_kwargs,
                "shadow_kwargs": shadow_kwargs,
                "owner": owner,
                "root": root,
                "_version": _version_value,
            }
        )
        _init_context.stack = stack

        try:
            super().__init__(**kwargs)
        except PydanticValidationError as e:
            from protean.fields.resolved import convert_pydantic_errors

            collected_errors.update(convert_pydantic_errors(e))

        # Check required descriptor fields (ValueObject, Reference, etc.)
        for field_name, field_obj in getattr(type(self), _FIELDS, {}).items():
            if (
                isinstance(field_obj, (ValueObject, Reference))
                and getattr(field_obj, "required", False)
                and field_name not in descriptor_kwargs
                and not any(
                    sk in shadow_kwargs
                    for sf in (
                        field_obj.embedded_fields.values()
                        if isinstance(field_obj, ValueObject)
                        else []
                    )
                    for sk in [sf.attribute_name]
                )
            ):
                collected_errors.setdefault(field_name, []).append("is required")

        if collected_errors:
            raise ValidationError(collected_errors)

    def model_post_init(self, __context: Any) -> None:
        if self.meta_.abstract is True:
            raise NotSupportedError(
                f"{self.__class__.__name__} class has been marked abstract"
                f" and cannot be instantiated"
            )

        # Pop init context from the thread-local stack (pushed by __init__)
        stack: list[dict[str, Any]] = getattr(_init_context, "stack", [])
        if stack:
            ctx = stack.pop()
            descriptor_kwargs: dict[str, Any] = ctx["descriptor_kwargs"]
            shadow_kwargs: dict[str, Any] = ctx["shadow_kwargs"]
            owner = ctx["owner"]
            root = ctx["root"]
            version_value = ctx.get("_version")
        else:
            descriptor_kwargs = {}
            shadow_kwargs = {}
            owner = None
            root = None
            version_value = None

        # Set hierarchy references
        if owner is not None:
            self._owner = owner
        if root is not None:
            self._root = root
        # Restore _version if provided (e.g. during repository hydration)
        if version_value is not None:
            self._version = version_value

        # Restore shadow field values directly into __dict__ (they bypass Pydantic)
        for name, value in shadow_kwargs.items():
            self.__dict__[name] = value

        # Reconstruct ValueObjects from shadow kwargs when the VO itself
        # wasn't explicitly provided (e.g. during repository retrieval).
        for field_name, field_obj in value_object_fields(self).items():
            if field_name not in descriptor_kwargs and not getattr(
                self, field_name, None
            ):
                # Gather shadow field values from shadow_kwargs
                vo_kwargs = {}
                for embedded_field in field_obj.embedded_fields.values():
                    vo_kwargs[embedded_field.field_name] = shadow_kwargs.get(
                        embedded_field.attribute_name
                    )
                # Only reconstruct if at least one value is not None
                if any(v is not None for v in vo_kwargs.values()):
                    descriptor_kwargs[field_name] = field_obj.value_object_cls(
                        **vo_kwargs
                    )

        # Set association/VO values via descriptors (triggers __set__).
        # Use object.__setattr__ to invoke the descriptor protocol directly,
        # bypassing the entity's __setattr__ which delegates to Pydantic for
        # unknown fields (descriptors are not Pydantic model fields).
        for name, value in descriptor_kwargs.items():
            object.__setattr__(self, name, value)

        # Discover invariants from MRO
        self._discover_invariants()

        self.defaults()

        # Initialize VO shadow fields to None when the VO itself is not set
        for field_obj in value_object_fields(self).values():
            for _, shadow_field in field_obj.get_shadow_fields():
                attr_name = shadow_field.attribute_name
                if attr_name not in self.__dict__:
                    self.__dict__[attr_name] = None

        # Initialize Reference shadow fields to None when not already set
        for field_obj in reference_fields(self).values():
            shadow_name, shadow = field_obj.get_shadow_field()
            if shadow_name not in self.__dict__:
                self.__dict__[shadow_name] = None

        # Setup association pseudo-methods (add_*, remove_*, get_one_from_*, filter_*)
        for field_name, field_obj in association_fields(self).items():
            getattr(self, field_name)  # Initialize/refresh associations

            if isinstance(field_obj, HasMany):
                setattr(self, f"add_{field_name}", partial(field_obj.add, self))
                setattr(self, f"remove_{field_name}", partial(field_obj.remove, self))
                setattr(
                    self, f"get_one_from_{field_name}", partial(field_obj.get, self)
                )
                setattr(self, f"filter_{field_name}", partial(field_obj.filter, self))

        # Run post-invariants after init
        errors = self._run_invariants("post", return_errors=True) or {}
        if errors:
            raise ValidationError(errors)

        self._initialized = True

    def _discover_invariants(self) -> None:
        """Scan class MRO for @invariant decorated methods and register them."""
        for klass in type(self).__mro__:
            for name, attr in vars(klass).items():
                if callable(attr) and hasattr(attr, "_invariant"):
                    self._invariants[attr._invariant][name] = attr

    def defaults(self) -> None:
        """Placeholder for defaults.

        Override in subclass when an attribute's default depends on other attribute values.
        """

    # ------------------------------------------------------------------
    # Data update (used by DAO.update)
    # ------------------------------------------------------------------
    def _update_data(self, *data_dict: dict[str, Any], **kwargs: Any) -> None:
        """Process and update entity values, collecting validation errors.

        :param data_dict: Dictionaries of values to be updated
        :param kwargs: keyword arguments with key-value pairs to be updated
        """
        errors: dict[str, list[str]] = {}

        for data in data_dict:
            if not isinstance(data, dict):
                raise AssertionError(
                    f"Positional argument {data} passed must be a dict. "
                    f"This argument serves as a template for loading common "
                    f"values.",
                )
            for field_name, val in data.items():
                try:
                    setattr(self, field_name, val)
                except ValidationError as err:
                    for fname in err.messages:
                        errors.setdefault(fname, []).extend(err.messages[fname])

        for field_name, val in kwargs.items():
            try:
                setattr(self, field_name, val)
            except ValidationError as err:
                for fname in err.messages:
                    errors.setdefault(fname, []).extend(err.messages[fname])

        if errors:
            logger.error(f"Errors on Update: {errors}")
            raise ValidationError(errors)

    # ------------------------------------------------------------------
    # Invariant checks
    # ------------------------------------------------------------------
    def _run_invariants(
        self, stage: str, return_errors: bool = False
    ) -> dict[str, list[str]] | None:
        """Run invariants for a given stage. Collect and return/raise errors.

        Also recursively walks associations (HasMany, HasOne) and ValueObject
        fields to run child-entity invariants, mirroring the legacy behavior.
        """
        if self._disable_invariant_checks:
            return {} if return_errors else None

        errors: dict[str, list[str]] = defaultdict(list)

        for invariant_method in self._invariants.get(stage, {}).values():
            try:
                invariant_method(self)
            except ValidationError as err:
                for field_name in err.messages:
                    errors[field_name].extend(err.messages[field_name])

        # Recursively run invariants on associated entities
        for field_name, field_obj in declared_fields(self).items():
            if isinstance(field_obj, Association):
                value = getattr(self, field_name)
                if value is not None:
                    items = value if isinstance(value, list) else [value]
                    for item in items:
                        if stage == "pre":
                            item_errors = item._precheck(return_errors=True)
                        else:
                            item_errors = item._postcheck(return_errors=True)
                        if item_errors:
                            for sub_field, error_list in item_errors.items():
                                errors[sub_field].extend(error_list)

        if return_errors:
            return dict(errors) if errors else {}

        if errors:
            raise ValidationError(errors)

        return None

    def _precheck(self, return_errors: bool = False):
        """Invariant checks performed before entity changes."""
        return self._run_invariants("pre", return_errors=return_errors)

    def _postcheck(self, return_errors: bool = False):
        """Invariant checks performed after initialization and attribute changes."""
        return self._run_invariants("post", return_errors=return_errors)

    # ------------------------------------------------------------------
    # Mutation with validation + invariant checks
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

            # Determine the target for invariant checks: aggregate root or self
            target = self._root if self._root is not None else self

            # Pre-check invariants
            target._precheck()

            # Delegate to Pydantic (validates via validate_assignment)
            try:
                super().__setattr__(name, value)
            except PydanticValidationError as e:
                from protean.fields.resolved import convert_pydantic_errors

                raise ValidationError(convert_pydantic_errors(e))

            # Post-check invariants
            target._postcheck()

            # Mark entity state as changed
            self._state.mark_changed()
        elif getattr(self, "_initialized", False) and (
            self._get_class_descriptor(type(self), name) is not None
        ):
            # Descriptor field: use object.__setattr__ to trigger descriptor protocol
            target = self._root if self._root is not None else self
            target._precheck()
            object.__setattr__(self, name, value)
            target._postcheck()
            self._state.mark_changed()
        elif name.startswith(("add_", "remove_", "get_one_from_", "filter_")):
            # Association pseudo-methods set during model_post_init
            object.__setattr__(self, name, value)
        elif (
            getattr(self, "_initialized", False)
            and not name.startswith("_")
            and name in self.__dict__
        ):
            # Shadow field (e.g., post_id for Reference descriptors) that was
            # previously initialised in model_post_init.  Write directly to
            # __dict__ to bypass Pydantic's validate_assignment.
            self.__dict__[name] = value
            if hasattr(self, "_state"):
                self._state.mark_changed()
        else:
            super().__setattr__(name, value)

    # ------------------------------------------------------------------
    # Hierarchy management
    # ------------------------------------------------------------------
    def _set_root_and_owner(self, root: Any, owner: Any) -> None:
        """Set the root and owner entities.

        Recursively descends into child entities to propagate the aggregate
        root reference.  Uses ``getattr`` so that descriptor-managed values
        (stored in ``state_.fields_cache``) are reached correctly.
        """
        self._root = root
        self._owner = owner

        for field_name, field_obj in association_fields(self).items():
            if isinstance(field_obj, HasMany):
                items = getattr(self, field_name, None) or []
                for item in items:
                    item._set_root_and_owner(root, self)
            elif isinstance(field_obj, HasOne):
                item = getattr(self, field_name, None)
                if item is not None:
                    item._set_root_and_owner(root, self)

    # ------------------------------------------------------------------
    # Event raising (delegates to aggregate root)
    # ------------------------------------------------------------------
    def raise_(self, event: Any) -> None:
        """Raise an event in the aggregate cluster.

        The event is always registered on the aggregate root, irrespective
        of where it is raised in the entity cluster.
        """
        if event.meta_.part_of != self._root.__class__:
            raise ConfigurationError(
                f"Event `{event.__class__.__name__}` is not associated with"
                f" aggregate `{self._root.__class__.__name__}`"
            )

        # Delegate to the root aggregate's raise_ (BaseAggregate overrides this)
        self._root.raise_(event)

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
        """Return entity data as a dictionary.

        Reference fields are skipped (they are navigation, not data).
        ValueObject fields are included only when non-None.
        """
        result: dict[str, Any] = {}
        for fname, field_obj in getattr(self, _FIELDS, {}).items():
            if isinstance(field_obj, Reference):
                continue

            value = getattr(self, fname, None)

            if isinstance(field_obj, ValueObject):
                # Only include non-None value objects
                dict_value = field_obj.as_dict(value)
                if dict_value:
                    result[fname] = dict_value
            elif isinstance(field_obj, Association):
                # HasOne/HasMany: delegate to descriptor's as_dict
                result[fname] = field_obj.as_dict(value)
            else:
                result[fname] = field_obj.as_dict(value)
        return result

    @property
    def state_(self) -> _EntityState:
        """Access entity lifecycle state."""
        return self._state

    @state_.setter
    def state_(self, value: _EntityState) -> None:
        self._state = value

    def __deepcopy__(self, memo: dict[int, Any] | None = None) -> "BaseEntity":
        """Deep copy that handles circular _root/_owner references.

        Pydantic's default __deepcopy__ recurses infinitely when
        __pydantic_private__ contains back-references to the entity
        itself (e.g. _root and _owner on aggregate roots).
        """
        import copy

        if memo is None:
            memo = {}

        # Short-circuit if we've already been copied (prevents infinite loop)
        existing = memo.get(id(self))
        if existing is not None:
            return existing

        cls = type(self)
        new_obj = cls.__new__(cls)
        memo[id(self)] = new_obj

        # Deep-copy __dict__ (Pydantic model fields and extras)
        object.__setattr__(new_obj, "__dict__", copy.deepcopy(self.__dict__, memo))
        object.__setattr__(
            new_obj,
            "__pydantic_extra__",
            copy.deepcopy(self.__pydantic_extra__, memo),
        )
        object.__setattr__(
            new_obj,
            "__pydantic_fields_set__",
            copy.copy(self.__pydantic_fields_set__),
        )

        # Deep-copy __pydantic_private__, with memo to break cycles
        private = getattr(self, "__pydantic_private__", None)
        if private is None:
            object.__setattr__(new_obj, "__pydantic_private__", None)
        else:
            object.__setattr__(
                new_obj,
                "__pydantic_private__",
                copy.deepcopy(private, memo),
            )

        return new_obj

    def __repr__(self) -> str:
        return "<%s: %s>" % (self.__class__.__name__, self)

    def __str__(self) -> str:
        id_field_name = getattr(self.__class__, _ID_FIELD_NAME, None)
        if id_field_name:
            identifier = getattr(self, id_field_name)
            return "%s object (%s)" % (
                self.__class__.__name__,
                "{}: {}".format(id_field_name, identifier),
            )
        return "%s object" % self.__class__.__name__


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def entity_factory(element_cls, domain, **opts):
    """Factory method to create an entity class.

    This method is used to create an entity class. It is called during domain registration.
    """
    # If opts has a `limit` key and it is negative, set it to None
    if "limit" in opts and opts["limit"] is not None and opts["limit"] < 0:
        opts["limit"] = None

    # Always route to Pydantic base
    base_cls = BaseEntity

    # Derive the entity class from the base entity class
    element_cls = derive_element_class(element_cls, base_cls, **opts)

    if not element_cls.meta_.part_of:
        raise IncorrectUsageError(
            f"Entity `{element_cls.__name__}` needs to be associated with an Aggregate"
        )

    # Set up reference fields for entities with part_of
    if not element_cls.meta_.abstract:
        reference_field = None
        for field_obj in declared_fields(element_cls).values():
            if isinstance(field_obj, Reference):
                # An explicit `Reference` field is already present
                reference_field = field_obj
                break

        if reference_field is None:
            # If no explicit Reference field is present, create one
            reference_field = Reference(element_cls.meta_.part_of)

            # If part_of is a string, set field name to inflection.underscore(part_of)
            #   Else, if it is a class, extract class name and set field name to inflection.underscore(class_name)
            if isinstance(element_cls.meta_.part_of, str):
                field_name = inflection.underscore(element_cls.meta_.part_of)
            else:
                field_name = inflection.underscore(element_cls.meta_.part_of.__name__)

            setattr(element_cls, field_name, reference_field)

            # Set the name of the field on itself
            reference_field.__set_name__(element_cls, field_name)

            # FIXME Centralize this logic to add fields dynamically to _FIELDS
            field_objects = getattr(element_cls, _FIELDS)
            field_objects[field_name] = reference_field
            setattr(element_cls, _FIELDS, field_objects)

        # Set up shadow fields for Reference fields
        for _, field_obj in getattr(element_cls, _FIELDS, {}).items():
            if isinstance(field_obj, Reference):
                shadow_field_name, shadow_field = field_obj.get_shadow_field()
                shadow_field.__set_name__(element_cls, shadow_field_name)

    # Iterate through methods marked as `@invariant` and record them for later use
    for klass in element_cls.__mro__:
        for method_name, method in vars(klass).items():
            if (
                not (method_name.startswith("__") and method_name.endswith("__"))
                and callable(method)
                and hasattr(method, "_invariant")
            ):
                element_cls._invariants[method._invariant][method_name] = method

    return element_cls


class invariant:
    @staticmethod
    def pre(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        setattr(wrapper, "_invariant", "pre")
        return wrapper

    @staticmethod
    def post(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        setattr(wrapper, "_invariant", "post")
        return wrapper
