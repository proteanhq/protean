"""Entity module providing the base class for entity domain elements."""

import copy
import functools
import inspect
import logging
import threading
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from enum import Enum
from functools import partial
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    NamedTuple,
    Self,
    TypeVar,
    cast,
    dataclass_transform,
    get_origin,
)
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, PrivateAttr
from pydantic import Field as PydanticField
from pydantic import ValidationError as PydanticValidationError
from pydantic.fields import FieldInfo

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
from protean.fields.association import Association, _ReferenceField
from protean.fields.basic import ValueObjectList
from protean.fields.embedded import _ShadowField
from protean.fields.resolved import ResolvedField, convert_pydantic_errors
from protean.fields.spec import FieldSpec, resolve_fieldspecs
from protean.fields.tempdata import AssociationCache, HasManyChanges, HasOneChanges
from protean.integrations.logging import (
    SECURITY_EVENT_INVARIANT_FAILED,
    log_security_event,
)
from protean.ir.diagnostics import DiagnosticCode
from protean.utils import (
    DomainObjects,
    _check_part_of_kind,
    _coerce_uuid_to_str,
    _derive_element_class,
    _ensure_template_dict,
    _generate_identity,
    inflection,
)
from protean.utils.container import DerivedDefault, Element, OptionsMixin
from protean.utils.globals import g
from protean.utils.reflection import (
    _FIELDS,
    _ID_FIELD_NAME,
    association_fields,
    declared_fields,
    reference_fields,
    value_object_fields,
)

if TYPE_CHECKING:
    from protean.core.value_object import BaseValueObject

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


class _EntitySnapshot(NamedTuple):
    """The state of one entity, kept to undo a change to it."""

    entity: Any
    values: dict[str, Any]
    fields_set: set[str]
    root: Any
    owner: Any
    flags: tuple[bool, bool, bool]
    cache: dict[str, Any]
    cache_items: dict[str, list[Any]]
    changes: dict[str, HasManyChanges | HasOneChanges]


def _copy_containers(value: Any) -> Any:
    """Copy nested lists and dicts, sharing the values inside them.

    A snapshot has to survive in-place changes such as ``tags.append(...)``,
    which a plain ``dict(__dict__)`` copy would share with the live entity.
    """
    if isinstance(value, list):
        return [_copy_containers(item) for item in value]
    if isinstance(value, dict):
        return {key: _copy_containers(item) for key, item in value.items()}
    return value


def _copy_values(entity: Any, values: dict[str, Any]) -> dict[str, Any]:
    # An association's list in ``__dict__`` is the same object as the one in
    # the fields cache, and ``_restore_entities`` relies on that, so it is not
    # copied here.
    associations = association_fields(entity)
    return {
        name: value if name in associations else _copy_containers(value)
        for name, value in values.items()
    }


def _snapshot_entity(entity: Any, copy_containers: bool = True) -> _EntitySnapshot:
    """Capture what a change can alter on ``entity``.

    Pass ``copy_containers=False`` when the snapshot is restored right after
    one assignment. An assignment replaces a value and never changes a list
    or dict in place, so the copy is only needed for a snapshot that has to
    outlast arbitrary code, such as an ``atomic_change`` block.
    """
    state = entity._state
    cache = state.fields_cache
    return _EntitySnapshot(
        entity=entity,
        values=(
            _copy_values(entity, entity.__dict__)
            if copy_containers
            else dict(entity.__dict__)
        ),
        fields_set=set(entity.__pydantic_fields_set__),
        root=entity._root,
        owner=entity._owner,
        flags=(state._new, state._changed, state._destroyed),
        cache=dict(cache),
        cache_items={
            name: list(value)
            for name, value in cache.items()
            if isinstance(value, list)
        },
        changes={name: changes.copy() for name, changes in entity._temp_cache.items()},
    )


def _snapshot_entity_trees(entities: list[Any]) -> list[_EntitySnapshot]:
    """Snapshot each entity in ``entities`` and every child loaded below it.

    The first snapshot is for ``entities[0]``. An association change touches
    the owner, the children it adds or removes, and the children of a removed
    child. Only values already in the fields cache are walked, so taking the
    snapshot never loads from the database.
    """
    seen: dict[int, Any] = {}
    pending = list(reversed(entities))
    while pending:
        entity = pending.pop()
        if not isinstance(entity, BaseEntity) or id(entity) in seen:
            continue
        seen[id(entity)] = entity
        cache = entity._state.fields_cache
        assert isinstance(cache, dict)
        for name in association_fields(entity):
            loaded = cache.get(name)
            pending.extend(loaded if isinstance(loaded, list) else [loaded])
    return [_snapshot_entity(entity) for entity in seen.values()]


def _restore_entities(snapshots: list[_EntitySnapshot]) -> None:
    """Put back what ``_snapshot_entity`` captured.

    Writes into the current ``__dict__``, because Pydantic's assignment
    validation replaces the ``__dict__`` object. Copies again on the way back,
    because one snapshot can sit in nested ``atomic_change`` blocks and be
    restored by each. Runs no validation and no invariants.
    """
    for snapshot in snapshots:
        entity = snapshot.entity
        entity.__dict__.clear()
        entity.__dict__.update(_copy_values(entity, snapshot.values))
        object.__setattr__(entity, "__pydantic_fields_set__", set(snapshot.fields_set))
        entity._root = snapshot.root
        entity._owner = snapshot.owner

        state = entity._state
        state._new, state._changed, state._destroyed = snapshot.flags

        cache = state.fields_cache
        cache.clear()
        cache.update(snapshot.cache)
        for name, items in snapshot.cache_items.items():
            cache[name][:] = items

        entity._temp_cache.clear()
        entity._temp_cache.update(
            {name: changes.copy() for name, changes in snapshot.changes.items()}
        )


@contextmanager
def _undo_on_failure(snapshots: list[_EntitySnapshot]) -> Iterator[None]:
    """Restore ``snapshots`` when the block raises, then re-raise."""
    try:
        yield
    except BaseException:
        _restore_entities(snapshots)
        raise


class _FieldsCacheDescriptor:
    def __get__(
        self, instance: Any, cls: type[Any] | None = None
    ) -> "_FieldsCacheDescriptor | dict[str, Any]":
        if instance is None:
            return self
        res = instance.fields_cache = {}
        return res


class _EntityState:
    """Store entity instance state."""

    def __init__(self) -> None:
        self._new = True
        self._changed = False
        self._destroyed = False

    @property
    def is_new(self) -> bool:
        return self._new

    @property
    def is_persisted(self) -> bool:
        return not self._new

    @property
    def is_changed(self) -> bool:
        return self._changed

    @property
    def is_destroyed(self) -> bool:
        return self._destroyed

    def mark_new(self) -> None:
        self._new = True

    def mark_saved(self) -> None:
        self._new = False
        self._changed = False

    mark_retrieved = (
        mark_saved  # Alias as placeholder so that future change wont affect interface
    )

    def mark_changed(self) -> None:
        if not (self._new or self._destroyed):
            self._changed = True

    def mark_destroyed(self) -> None:
        self._destroyed = True
        self._changed = False

    fields_cache = _FieldsCacheDescriptor()


# ---------------------------------------------------------------------------
# BaseEntity
# ---------------------------------------------------------------------------
# Entities are constructed by keyword only (pydantic's ``__init__`` takes
# ``**data``), so field order does not matter to a type checker.
@dataclass_transform(
    kw_only_default=True,
    field_specifiers=(FieldSpec, HasMany, HasOne, Reference, ValueObject),
)
class BaseEntity(Element, BaseModel, OptionsMixin):
    """Base class for entities, domain objects with a unique identity that
    live within an aggregate.

    Entities are mutable. Two entities are equal when they have the same
    identifier, whatever their other attribute values. Assigning a field
    validates the new value and runs the entity's pre and post invariants.

    Fields are declared with Python type annotations and optional ``Field``
    constraints. An ``id`` identity field is added unless one is declared
    with ``identifier=True``.

    The ``state_`` property reports whether the entity is new, persisted,
    changed or destroyed. Events an entity raises are recorded on its
    aggregate root. See the entities guide.

    **Meta Options**

    | Option | Type | Description |
    |--------|------|-------------|
    | ``part_of`` | ``type`` | The aggregate this entity belongs to, or the parent entity for a nested entity. Required. |
    | ``database`` | ``str`` | The ``[databases.*]`` entry that persists it (default: ``"default"``). |
    | ``schema_name`` | ``str`` | The storage table/collection name. |
    | ``auto_add_id_field`` | ``bool`` | Whether to auto-inject an ``id`` field (default: ``True``). |
    """

    element_type: ClassVar[str] = DomainObjects.ENTITY

    if TYPE_CHECKING:
        # Assigned per-subclass in ``__init_subclass__`` via
        # ``setattr(cls, "_invariants", defaultdict(dict))``; declared here only
        # so static checkers see the attribute. Keyed by invariant stage
        # ("pre"/"post") → {method_name: method}.
        _invariants: ClassVar[defaultdict[str, dict[str, Callable[..., Any]]]]

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
    _temp_cache: AssociationCache = PrivateAttr(default_factory=AssociationCache)
    _events: list[Any] = PrivateAttr(default_factory=list)
    _disable_invariant_checks: bool = PrivateAttr(default=False)
    # One snapshot list per open ``atomic_change`` block on this aggregate. An
    # association change inside a block adds the children it links, so the
    # block can undo the link when it fails.
    _atomic_snapshots: list[list["_EntitySnapshot"]] = PrivateAttr(default_factory=list)
    # Set True only for the duration of an ``@apply`` handler during event
    # replay (by ``BaseAggregate._apply``). While set, ``__setattr__`` drops an
    # assignment to a reserved (removed) field name instead of raising, and
    # ``BaseAggregate.__getattr__`` turns the ``add_``/``remove_`` helpers of a
    # reserved name into no-ops.
    _replaying: bool = PrivateAttr(default=False)

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        if cls is BaseEntity:
            raise NotSupportedError("BaseEntity cannot be instantiated")
        return super().__new__(cls)

    _default_options: ClassVar[list[tuple[str, Any]]] = [
        ("aggregate_cluster", None),
        ("auto_add_id_field", True),
        ("indexes", ()),
        ("part_of", None),
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

        # Initialize invariant storage
        cls._invariants = defaultdict(dict)
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
        # Migrate annotation-style descriptors to the class namespace.
        #
        # Python puts ``field: Descriptor()`` values into ``__annotations__``
        # (not ``vars(cls)``).  Pydantic and our ``__pydantic_init_subclass__``
        # scan ``vars(cls)`` for descriptors, so they must live there.
        # We also explicitly trigger ``__set_name__`` because ``setattr``
        # does NOT invoke it (only class-body execution does).
        #
        # In the typed-annotation style (``entries: list[Entry] =
        # HasMany(Entry)``) the descriptor is already in ``vars(cls)``, but
        # the type annotation stays behind. Pydantic would then build a model
        # field from that annotation, which shadows the descriptor and makes
        # the field required, so the annotation is dropped here too.
        own_annots: dict[str, Any] = inspect.get_annotations(cls)
        namespace = vars(cls)
        to_remove: list[str] = []
        for name, value in list(own_annots.items()):
            if isinstance(value, _DESCRIPTOR_TYPES):
                setattr(cls, name, value)
                if hasattr(value, "__set_name__"):
                    value.__set_name__(cls, name)
                to_remove.append(name)
            elif isinstance(namespace.get(name), _DESCRIPTOR_TYPES):
                to_remove.append(name)
        if to_remove:
            annots = dict(own_annots)
            for name in to_remove:
                del annots[name]
            cls.__annotations__ = annots

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
        if _is_auto_id_exempt(cls):
            return

        own_annots: dict[str, Any] = inspect.get_annotations(cls)

        if (
            _class_attrs_declare_identifier(cls)
            or any(_annotation_declares_identifier(a) for a in own_annots.values())
            or _ancestors_declare_identifier(cls)
        ):
            return

        if "id" not in own_annots:
            _inject_auto_id(cls, own_annots)

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
                        (
                            f"Multiple identifier fields found in entity {cls.__name__}. "
                            "Only one identifier field is allowed."
                        )
                    ]
                }
            )
        elif len(id_fields) == 1:
            setattr(cls, _ID_FIELD_NAME, id_fields[0].field_name)

    @staticmethod
    def _get_class_descriptor(klass: type[Any], name: str) -> Any:
        """Look up a descriptor on the class MRO without triggering __get__.

        ``getattr(cls, name)`` invokes the data descriptor protocol, which
        may return ``None`` or ``[]`` for association descriptors.  Scanning
        ``__dict__`` directly returns the raw descriptor object.
        """
        for mro_cls in klass.__mro__:
            if name in vars(mro_cls):
                attr = vars(mro_cls)[name]
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
        entity_cls = type(self)
        values = _split_init_values(
            args,
            kwargs,
            _shadow_field_names(entity_cls),
            lambda name: self._get_class_descriptor(entity_cls, name) is not None,
        )
        descriptor_kwargs = values.descriptor_kwargs
        shadow_kwargs = values.shadow_kwargs

        # Collect all validation errors (Pydantic + required descriptors) before raising
        collected_errors: dict[str, list[str]] = {}

        # Push init context onto the thread-local stack so that
        # model_post_init (called by Pydantic inside super().__init__())
        # can retrieve descriptor/shadow kwargs.  Pydantic wipes __dict__
        # during validation, so we cannot stash data on the instance.
        stack: list[dict[str, Any]] = getattr(_init_context, "stack", [])
        depth_before_init = len(stack)
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
            super().__init__(**values.kwargs)
        except PydanticValidationError as e:
            collected_errors.update(convert_pydantic_errors(e))
        finally:
            # ``model_post_init`` pops this call's entry on a successful init.
            # When construction raises before it runs (Pydantic field validation
            # fails, or an abstract class is rejected), the entry is left behind,
            # and a caller that catches the error in a loop (the snapshot loader
            # reloading a stale aggregate) leaks one entry per attempt. Truncate
            # to the pre-push depth so this call's entry is balanced for any
            # construction exception, without popping a parent or double-popping
            # one ``model_post_init`` already removed.
            del stack[depth_before_init:]

        _add_missing_required_errors(
            entity_cls, descriptor_kwargs, shadow_kwargs, collected_errors
        )

        if collected_errors:
            raise ValidationError(collected_errors)

    def model_post_init(self, context: Any, /) -> None:
        if self.meta_.abstract is True:
            raise NotSupportedError(
                f"{self.__class__.__name__} class has been marked abstract"
                f" and cannot be instantiated"
            )

        # Pop init context from the thread-local stack (pushed by __init__)
        ctx = _pop_init_context(_init_context)
        descriptor_kwargs: dict[str, Any] = ctx["descriptor_kwargs"]
        shadow_kwargs: dict[str, Any] = ctx["shadow_kwargs"]

        _apply_hierarchy(self, ctx)

        _write_shadow_values(self, shadow_kwargs)
        _rebuild_value_objects(self, descriptor_kwargs, shadow_kwargs)

        _set_descriptor_values(self, descriptor_kwargs, shadow_kwargs)

        # Discover invariants from MRO
        self._discover_invariants()

        self.defaults()

        _init_value_object_shadows(self)
        _init_reference_shadows(self)
        _attach_association_methods(self)
        _raise_post_init_invariants(self)

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
            _ensure_template_dict(data)
            _collect_setattr_errors(self, data, errors)

        _collect_setattr_errors(self, kwargs, errors)

        if errors:
            logger.error(f"Errors on Update: {errors}")
            raise ValidationError(errors)

    # ------------------------------------------------------------------
    # Invariant checks
    # ------------------------------------------------------------------
    def _run_invariants(
        self,
        stage: str,
        return_errors: bool = False,
        fired_codes: list[str] | None = None,
    ) -> dict[str, list[str]] | None:
        """Run invariants for a given stage. Collect and return/raise errors.

        Also recursively walks associations (HasMany, HasOne) to run child-entity
        invariants, mirroring the legacy behavior.

        ``fired_codes`` accumulates the diagnostic code of every invariant that
        fails, at this level and recursively in child entities, so the top-level
        raise (here, or after construction in ``model_post_init``) can attach
        them all. A caller aggregating
        with ``return_errors=True`` passes its own list; the internal raise below
        builds one when none is given.
        """
        if self._disable_invariant_checks:
            return {} if return_errors else None

        errors: dict[str, list[str]] = defaultdict(list)
        codes = fired_codes if fired_codes is not None else []

        failed_invariants = _run_own_invariants(self, stage, errors, codes)
        _run_association_invariants(self, stage, errors, codes)

        if return_errors:
            return dict(errors) if errors else {}

        if errors:
            # A plain dict, so a missing key raises KeyError on every path,
            # the same as the dict that construction raises.
            messages = dict(errors)
            # Only the outer raise site logs. Nested calls pass
            # ``return_errors=True`` and return before this point, so a failure
            # in an associated entity is logged once, for the root.
            self._emit_invariant_failed(stage, failed_invariants, messages)
            raise ValidationError(
                messages,
                codes=codes,
                location=type(self).__qualname__,
            )

        return None

    def _emit_invariant_failed(
        self,
        stage: str,
        failed_invariants: list[str],
        errors: dict[str, list[str]],
    ) -> None:
        """Log an ``invariant_failed`` WARNING on ``protean.security`` for each
        failed invariant.

        Logs only while a message is being handled (``g.message_in_context``
        is set). Outside a handler it logs nothing.
        """
        # Imported here to break a circular import: ``domain/__init__.py`` ->
        # ``adapters`` -> ``core.projection`` -> ``core.entity``.
        from protean.domain.context import has_domain_context  # noqa: PLC0415

        # A failed invariant is a security signal only when it surfaces during
        # message handling. Fixtures, unit tests on raw aggregates, and code
        # that catches and retries stay off the channel.
        if not has_domain_context() or g.get("message_in_context") is None:
            return

        id_field_name = getattr(self.__class__, _ID_FIELD_NAME, None)
        aggregate_id = str(getattr(self, id_field_name, "")) if id_field_name else ""
        # Fall back to field names so operators still see a useful signal when
        # the error came from nested state without a method name (e.g.
        # association-level errors collected recursively).
        names = failed_invariants or sorted(errors.keys())
        for invariant_name in names:
            log_security_event(
                SECURITY_EVENT_INVARIANT_FAILED,
                aggregate=self.__class__.__name__,
                aggregate_id=aggregate_id,
                invariant=invariant_name,
                stage=stage,
            )

    def _precheck(
        self, return_errors: bool = False, fired_codes: list[str] | None = None
    ) -> dict[str, list[str]] | None:
        """Invariant checks performed before entity changes."""
        return self._run_invariants(
            "pre", return_errors=return_errors, fired_codes=fired_codes
        )

    def _postcheck(
        self, return_errors: bool = False, fired_codes: list[str] | None = None
    ) -> dict[str, list[str]] | None:
        """Invariant checks performed after initialization and attribute changes."""
        return self._run_invariants(
            "post", return_errors=return_errors, fired_codes=fired_codes
        )

    # ------------------------------------------------------------------
    # Status transition validation
    # ------------------------------------------------------------------
    def _validate_status_transition(self, field_name: str, new_value: Any) -> None:
        """Validate that a status field transition is legal.

        Called from ``__setattr__`` when invariant checks are active.
        Skipped during ``atomic_change`` (deferred to ``__exit__``),
        ``from_events`` replay, and initial construction.
        """

        fields_dict = getattr(self.__class__, _FIELDS, {})
        field_obj = fields_dict.get(field_name)
        if field_obj is None or not isinstance(field_obj, ResolvedField):
            return
        transitions = field_obj.transitions
        if not transitions:
            return

        current_value = getattr(self, field_name, None)

        # Normalize to string values
        target = new_value.value if isinstance(new_value, Enum) else new_value
        current = (
            current_value.value if isinstance(current_value, Enum) else current_value
        )

        # None -> any value is allowed (initial assignment / reconstitution)
        if current is None:
            return

        if current not in transitions:
            raise ValidationError(
                {
                    field_name: [
                        (
                            f"Invalid status transition from '{current}'. "
                            f"'{current}' is a terminal state with no allowed transitions"
                        )
                    ]
                }
            )

        allowed = transitions[current]
        if target not in allowed:
            if current == target:
                msg = (
                    f"Re-entry into '{current}' is not allowed. "
                    f"If this operation should be idempotent, "
                    f"add '{current}' to its own target list in transitions"
                )
            else:
                allowed_str = ", ".join(allowed)
                msg = (
                    f"Invalid status transition from '{current}' to '{target}'. "
                    f"Allowed transitions: {allowed_str}"
                )
            raise ValidationError({field_name: [msg]})

    def can_transition_to(self, field_name: str, target_value: Any) -> bool:
        """Check whether a status field can transition to the given value.

        Returns ``True`` if the transition is valid, ``False`` otherwise.
        Always returns ``True`` for non-status fields or status fields
        without a transitions map.

        Example::

            if order.can_transition_to("status", OrderStatus.SHIPPED):
                order.ship(tracking_number="ABC123")
        """

        fields_dict = getattr(self.__class__, _FIELDS, {})
        field_obj = fields_dict.get(field_name)
        if field_obj is None or not isinstance(field_obj, ResolvedField):
            return True
        transitions = field_obj.transitions
        if not transitions:
            return True

        current_value = getattr(self, field_name, None)
        target = target_value.value if isinstance(target_value, Enum) else target_value
        current = (
            current_value.value if isinstance(current_value, Enum) else current_value
        )

        if current is None:
            return True

        if current not in transitions:
            return False

        return target in transitions[current]

    # ------------------------------------------------------------------
    # Mutation with validation + invariant checks
    # ------------------------------------------------------------------
    def _snapshot_assignment(self, target: "BaseEntity") -> list[_EntitySnapshot]:
        """Snapshot this entity before a plain, value object or ``Reference`` write.

        With invariant checks off on ``target``, the post-check after the
        assignment does nothing, so there is nothing to undo. That covers
        event replay, and every assignment inside an ``atomic_change`` block,
        whose entry snapshot already holds this entity.
        """
        if target._disable_invariant_checks:
            return []
        return [_snapshot_entity(self, copy_containers=False)]

    def _snapshot_association_change(
        self, target: "BaseEntity", name: str, descriptor: Any, incoming: Any
    ) -> list[_EntitySnapshot]:
        """Snapshot what a change to the association ``name`` can touch.

        That is this entity and the ``incoming`` children with their own
        children, because the association links each incoming child to this
        entity. A ``HasOne`` replacement or an empty ``HasMany`` assignment
        also drops the current children, so those and their own children are
        included too. Children the change cannot touch are left out, so
        repeated ``add_<field>()`` calls do not copy the whole aggregate each
        time.

        With invariant checks off and no ``atomic_change`` block open, as in
        event replay, nothing can use the snapshot, so none is taken.
        """
        if target._disable_invariant_checks and not target._atomic_snapshots:
            return []
        cache = self._state.fields_cache
        assert isinstance(cache, dict)
        items = incoming if isinstance(incoming, list) else [incoming]
        if isinstance(descriptor, HasOne) or all(item is None for item in items):
            current = cache.get(name)
            items = [*items, *(current if isinstance(current, list) else [current])]
        return [_snapshot_entity(self), *_snapshot_entity_trees(items)]

    def _add_to_open_blocks(self, snapshots: list[_EntitySnapshot]) -> None:
        """Add ``snapshots`` to every ``atomic_change`` block open on this aggregate.

        A block's entry snapshot holds only the entities present at entry, so
        a child linked inside the block is added here for the block to undo.
        """
        for block in self._atomic_snapshots:
            known = {id(snapshot.entity) for snapshot in block}
            block.extend(
                snapshot for snapshot in snapshots if id(snapshot.entity) not in known
            )

    def _change_association(
        self, name: str, operation: Callable[[Any, Any], None], items: Any
    ) -> None:
        """Run an ``add_<name>`` or ``remove_<name>`` call, undoing it on failure.

        The association methods run the root's invariant checks themselves.
        When one of them fails, the field's children and pending changes go
        back to what they were before the call.
        """
        target = self._root if self._root is not None else self
        snapshots = self._snapshot_association_change(
            target, name, self._get_class_descriptor(type(self), name), items
        )
        target._add_to_open_blocks(snapshots)
        with _undo_on_failure(snapshots):
            operation(self, items)

    def __setattr__(self, name: str, value: Any) -> None:
        # During event replay only, drop an assignment to a reserved (removed)
        # field name. A retained ``@apply`` handler for a retired event can
        # still target a name whose field is gone; replay must tolerate it. The
        # live ``raise_`` path never sets ``_replaying``, so a live write to a
        # removed field still falls through to ``extra="forbid"`` and raises. A
        # name that is neither a field nor reserved also falls through and
        # raises, so a typo in a retained handler stays an error. Calls to the
        # ``add_``/``remove_`` helpers of a reserved name are dropped in
        # ``BaseAggregate.__getattr__``.
        if _drops_reserved_on_replay(self, name):
            return

        if name in self.__class__.model_fields and getattr(self, "_initialized", False):
            target, snapshots = _precheck_model_field(self, name, value)

            # Delegate to Pydantic (validates via validate_assignment)
            try:
                super().__setattr__(name, value)
            except PydanticValidationError as e:
                raise ValidationError(convert_pydantic_errors(e)) from e

            # Post-check invariants. A failure undoes this one assignment.
            with _undo_on_failure(snapshots):
                target._postcheck()

            # Mark entity state as changed
            self._state.mark_changed()
        elif getattr(self, "_initialized", False) and (
            (descriptor := self._get_class_descriptor(type(self), name)) is not None
        ):
            _set_descriptor_field(self, name, descriptor, value)
        elif name.startswith(("add_", "remove_", "get_one_from_", "filter_")):
            # Association pseudo-methods set during model_post_init
            object.__setattr__(self, name, value)
        elif _is_shadow_field_write(self, name):
            _set_shadow_field(self, name, value)
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
                # Present, not truthy: ``as_dict`` returns ``None`` only
                # when the VO is ``None``, so an all-default VO is still included.
                dict_value = field_obj.as_dict(value)
                if dict_value is not None:
                    result[fname] = dict_value
            elif isinstance(field_obj, Association):
                # HasOne/HasMany: delegate to descriptor's as_dict
                result[fname] = field_obj.as_dict(value)
            else:
                result[fname] = field_obj.as_dict(value)
        return result

    @classmethod
    def from_value_object(cls, vo: "BaseValueObject") -> Self:
        """Construct an entity instance from a value object.

        This is the inverse of ``value_object_from_entity()`` -- it converts
        a VO payload (typically carried in a command or event) back into an
        entity instance::

            items = [OrderItem.from_value_object(item) for item in command.items]

        ``None`` values on identifier/unique fields are stripped so that
        auto-generated identity fields receive their default rather than
        failing validation.  Explicit ``None`` on other fields is preserved.
        """
        data = vo.to_dict()

        # Strip None only for identifier/unique fields so auto-generated
        # identity defaults kick in, while preserving intentional Nones.
        id_or_unique = set()
        for fname, field_obj in getattr(cls, _FIELDS, {}).items():
            if isinstance(field_obj, ResolvedField) and (
                field_obj.identifier or field_obj.unique
            ):
                id_or_unique.add(fname)

        return cls(
            **{k: v for k, v in data.items() if not (v is None and k in id_or_unique)}
        )

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
        if memo is None:
            memo = {}

        # Short-circuit if we've already been copied (prevents infinite loop)
        existing: BaseEntity | None = memo.get(id(self))
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
        return f"<{self.__class__.__name__}: {self}>"

    def __str__(self) -> str:
        id_field_name = getattr(self.__class__, _ID_FIELD_NAME, None)
        if id_field_name:
            identifier = getattr(self, id_field_name)
            return "{} object ({})".format(
                self.__class__.__name__,
                f"{id_field_name}: {identifier}",
            )
        return f"{self.__class__.__name__} object"


# ---------------------------------------------------------------------------
# BaseEntity helpers
# ---------------------------------------------------------------------------
# These are module-level functions so a user subclass that defines a method
# with the same name cannot replace them.


def _is_auto_id_exempt(cls: type[BaseEntity]) -> bool:
    """Return ``True`` when ``_maybe_inject_auto_id`` must leave ``cls`` alone.

    That is the framework base classes themselves, and classes built by
    ``_prepare_pydantic_namespace`` (marked with ``__auto_id_handled__``).
    """
    if cls.__name__ in ("BaseEntity", "BaseAggregate"):
        return True
    return bool(vars(cls).get("__auto_id_handled__"))


def _field_info_is_identifier(value: Any) -> bool:
    """Return ``True`` when ``value`` is a ``FieldInfo`` marked ``identifier``."""
    if not isinstance(value, FieldInfo):
        return False
    extra = value.json_schema_extra
    return isinstance(extra, dict) and bool(extra.get("identifier"))


def _class_attrs_declare_identifier(cls: type[BaseEntity]) -> bool:
    """Return ``True`` when a class-level ``FieldInfo`` declares an identifier."""
    return any(_field_info_is_identifier(value) for value in vars(cls).values())


def _annotation_declares_identifier(annot_value: Any) -> bool:
    """Return ``True`` when an annotation declares an identifier field.

    Handles ``Annotated`` written as a lazy string as well as a resolved type.
    """
    if isinstance(annot_value, str):
        double_quoted = '"identifier": True' in annot_value
        return double_quoted or "'identifier': True" in annot_value
    # Handle resolved Annotated types (no from __future__). A plain class is
    # free to carry an unrelated ``__metadata__`` attribute, so ask
    # ``get_origin`` rather than sniffing for the attribute.
    if get_origin(annot_value) is Annotated:
        return any(_field_info_is_identifier(m) for m in annot_value.__metadata__)
    return False


def _ancestors_declare_identifier(cls: type[BaseEntity]) -> bool:
    """Return ``True`` when an inherited ``__container_fields__`` has an identifier."""
    return any(
        getattr(fobj, "identifier", False)
        for parent in cls.__mro__[1:]
        for fobj in getattr(parent, _FIELDS, {}).values()
    )


def _inject_auto_id(cls: type[BaseEntity], own_annots: dict[str, Any]) -> None:
    """Add an auto-generated ``id`` identifier field to ``cls``."""
    annots = dict(own_annots)
    annots["id"] = Annotated[str | int | UUID, BeforeValidator(_coerce_uuid_to_str)]
    cls.__annotations__ = annots
    setattr(
        cls,
        "id",
        PydanticField(
            default_factory=_generate_identity,
            validate_default=True,
            json_schema_extra={
                "identifier": True,
                "_auto_generated": True,
            },
        ),
    )


class _InitValues(NamedTuple):
    """The values passed to ``__init__``, split by where they go."""

    kwargs: dict[str, Any]
    descriptor_kwargs: dict[str, Any]
    shadow_kwargs: dict[str, Any]


def _value_object_shadow_names(field_obj: ValueObject) -> set[str]:
    """Return the shadow attribute names of a ``ValueObject`` field."""
    return {
        sf.attribute_name
        for sf in field_obj.embedded_fields.values()
        if sf.attribute_name is not None
    }


def _shadow_field_names(entity_cls: type[BaseEntity]) -> set[str]:
    """Return the shadow field names of the ``Reference`` and ``ValueObject`` fields.

    Only these names are taken out of the ``__init__`` values, so a truly
    unknown keyword still reaches Pydantic, which rejects it.
    """
    names: set[str] = set()
    for fobj in getattr(entity_cls, _FIELDS, {}).values():
        if isinstance(fobj, Reference):
            attr_name = fobj.get_attribute_name()
            if attr_name:
                names.add(attr_name)
        elif isinstance(fobj, ValueObject):
            names |= _value_object_shadow_names(fobj)
    return names


def _separate_init_kwargs(
    values: dict[str, Any],
    shadow_names: set[str],
    is_descriptor: Callable[[str], bool],
    into: _InitValues,
) -> None:
    """Pop shadow field and descriptor keys from ``values`` into ``into``."""
    for name in list(values):
        if name in shadow_names:
            into.shadow_kwargs[name] = values.pop(name)
        elif is_descriptor(name):
            into.descriptor_kwargs[name] = values.pop(name)


def _split_init_values(
    templates: tuple[Any, ...],
    kwargs: dict[str, Any],
    shadow_names: set[str],
    is_descriptor: Callable[[str], bool],
) -> _InitValues:
    """Split the template dicts and keyword arguments passed to ``__init__``.

    Shadow field and descriptor keys are popped from ``kwargs`` and then from
    each template dict, in place. The remaining keys are merged into the
    returned ``kwargs``, with keyword arguments winning over template values.
    """
    values = _InitValues(kwargs, {}, {})
    _separate_init_kwargs(kwargs, shadow_names, is_descriptor, values)
    if not templates:
        return values

    # Support template dict pattern: Entity({"key": "val"}, key2="val2")
    merged: dict[str, Any] = {}
    for template in templates:
        _ensure_template_dict(template)
        _separate_init_kwargs(template, shadow_names, is_descriptor, values)
        merged.update(template)
    merged.update(kwargs)
    return values._replace(kwargs=merged)


def _has_shadow_value(field_obj: Any, shadow_kwargs: dict[str, Any]) -> bool:
    """Return ``True`` when a shadow field of ``field_obj`` was given.

    For example ``region_id`` for a ``region`` Reference.
    """
    if isinstance(field_obj, ValueObject):
        return any(
            sf.attribute_name in shadow_kwargs
            for sf in field_obj.embedded_fields.values()
        )
    return field_obj.get_attribute_name() in shadow_kwargs


def _add_missing_required_errors(
    element_cls: type[Any],
    descriptor_kwargs: dict[str, Any],
    shadow_kwargs: dict[str, Any],
    collected_errors: dict[str, list[str]],
) -> None:
    """Add an ``is required`` error for each required descriptor field not given.

    ``element_cls`` is an entity, aggregate or projection class. Covers
    ``ValueObject`` and ``Reference`` fields. A field counts as given when its
    own name or one of its shadow fields was passed.
    """
    for field_name, field_obj in getattr(element_cls, _FIELDS, {}).items():
        if (
            isinstance(field_obj, (ValueObject, Reference))
            and getattr(field_obj, "required", False)
            and field_name not in descriptor_kwargs
            and not _has_shadow_value(field_obj, shadow_kwargs)
        ):
            collected_errors.setdefault(field_name, []).append("is required")


def _set_descriptor_values(
    element: Any,
    descriptor_kwargs: dict[str, Any],
    shadow_kwargs: dict[str, Any],
) -> None:
    """Set each association or value object field given in ``descriptor_kwargs``.

    Raises ``ValidationError`` when a field rejects its value. The error holds
    every rejected field's messages and an ``is required`` error for each
    required descriptor field not given.
    """
    errors: dict[str, list[str]] = {}
    for name, value in descriptor_kwargs.items():
        try:
            # object.__setattr__ runs the descriptor's __set__ directly. The
            # element's own __setattr__ hands unknown names to Pydantic, and
            # descriptors are not Pydantic model fields.
            object.__setattr__(element, name, value)
        except ValidationError as err:
            # Pydantic does not wrap a Protean error raised in model_post_init,
            # so the caller's __init__ never adds the missing required fields.
            # Collect them here to report every field's error together.
            by_field = (
                err.messages if isinstance(err.messages, dict) else {name: [str(err)]}
            )
            for key, key_messages in by_field.items():
                errors.setdefault(key, []).extend(key_messages)

    if errors:
        _add_missing_required_errors(
            type(element), descriptor_kwargs, shadow_kwargs, errors
        )
        raise ValidationError(errors)


def _pop_init_context(local: threading.local) -> dict[str, Any]:
    """Pop the init context ``__init__`` pushed onto ``local.stack``.

    Returns empty descriptor and shadow kwargs and no owner or root when the
    stack is empty.
    """
    stack: list[dict[str, Any]] = getattr(local, "stack", [])
    if stack:
        return stack.pop()
    return {"descriptor_kwargs": {}, "shadow_kwargs": {}, "owner": None, "root": None}


def _apply_hierarchy(entity: BaseEntity, ctx: dict[str, Any]) -> None:
    """Set the owner, root and version the init context carries."""
    owner = ctx["owner"]
    root = ctx["root"]
    version_value = ctx.get("_version")
    if owner is not None:
        entity._owner = owner
    if root is not None:
        entity._root = root
    # Restore _version if provided (e.g. during repository hydration)
    if version_value is not None:
        entity._version = version_value


def _write_shadow_values(instance: BaseModel, shadow_kwargs: dict[str, Any]) -> None:
    """Write shadow field values straight into ``__dict__``, bypassing Pydantic."""
    for name, value in shadow_kwargs.items():
        instance.__dict__[name] = value  # pyright: ignore[reportIndexIssue]


def _value_object_kwargs_from_shadows(
    field_obj: ValueObject, shadow_kwargs: dict[str, Any]
) -> dict[str, Any]:
    """Return the value object's field values found in ``shadow_kwargs``.

    Only the keys the caller gave are returned, so the value object's own
    defaults fill the rest. Filling them with ``None`` fails on any field that
    does not accept it.
    """
    vo_kwargs: dict[str, Any] = {}
    for embedded_field in field_obj.embedded_fields.values():
        # ``embedded_fields`` yields fully-bound fields, so both names are
        # always set; the asserts only narrow the types.
        assert embedded_field.attribute_name is not None
        assert embedded_field.field_name is not None
        if embedded_field.attribute_name in shadow_kwargs:
            vo_kwargs[embedded_field.field_name] = shadow_kwargs[
                embedded_field.attribute_name
            ]
    return vo_kwargs


def _rebuild_value_objects(
    instance: Element,
    descriptor_kwargs: dict[str, Any],
    shadow_kwargs: dict[str, Any],
) -> None:
    """Add to ``descriptor_kwargs`` each value object rebuilt from shadow kwargs.

    A value object is rebuilt only when it was not passed itself, is not
    already set (for example during repository retrieval), and at least one of
    its shadow values is not ``None``.
    """
    for field_name, base_field_obj in value_object_fields(instance).items():
        # ``value_object_fields`` filters on ``isinstance(_, ValueObject)``,
        # so every entry is a ``ValueObject`` at runtime; narrow the
        # base-typed reflection return so the VO-only attributes resolve.
        field_obj = cast(ValueObject, base_field_obj)
        # Identity, not truthiness: an already-set all-default VO is
        # falsy but present and must not be clobbered by a shadow rebuild.
        if (
            field_name in descriptor_kwargs
            or getattr(instance, field_name, None) is not None
        ):
            continue
        vo_kwargs = _value_object_kwargs_from_shadows(field_obj, shadow_kwargs)
        # Only reconstruct if at least one value is not None
        if any(v is not None for v in vo_kwargs.values()):
            # ``value_object_cls`` is a resolved class at this point; the
            # property in ``fields/embedded.py`` widens it to
            # ``type[BaseValueObject] | str``, so narrow before calling.
            vo_cls = field_obj.value_object_cls
            assert not isinstance(vo_cls, str)
            descriptor_kwargs[field_name] = vo_cls(**vo_kwargs)


def _init_value_object_shadows(instance: Element) -> None:
    """Set each value object shadow field not yet in ``__dict__`` to ``None``."""
    for base_field_obj in value_object_fields(instance).values():
        field_obj = cast(ValueObject, base_field_obj)
        for _, shadow_field in field_obj.get_shadow_fields():
            attr_name = shadow_field.attribute_name
            if attr_name is not None and attr_name not in instance.__dict__:
                # pyright models pydantic ``__dict__`` as a read-only
                # MappingProxyType; writing to it is valid at runtime.
                instance.__dict__[attr_name] = None  # pyright: ignore[reportIndexIssue]


def _init_reference_shadows(entity: BaseEntity) -> None:
    """Set each ``Reference`` shadow field not yet in ``__dict__`` to ``None``."""
    for base_ref_obj in reference_fields(entity).values():
        ref_obj = cast(Reference, base_ref_obj)
        shadow_name, _shadow = ref_obj.get_shadow_field()
        if shadow_name is not None and shadow_name not in entity.__dict__:
            entity.__dict__[shadow_name] = None  # pyright: ignore[reportIndexIssue]


def _attach_association_methods(entity: BaseEntity) -> None:
    """Load each association and set the ``HasMany`` pseudo-methods.

    The pseudo-methods are ``add_*``, ``remove_*``, ``get_one_from_*`` and
    ``filter_*``.
    """
    for field_name, assoc_obj in association_fields(entity).items():
        getattr(entity, field_name)  # Initialize/refresh associations

        if isinstance(assoc_obj, HasMany):
            setattr(
                entity,
                f"add_{field_name}",
                partial(entity._change_association, field_name, assoc_obj.add),
            )
            setattr(
                entity,
                f"remove_{field_name}",
                partial(entity._change_association, field_name, assoc_obj.remove),
            )
            setattr(
                entity, f"get_one_from_{field_name}", partial(assoc_obj.get, entity)
            )
            setattr(entity, f"filter_{field_name}", partial(assoc_obj.filter, entity))


def _raise_post_init_invariants(entity: BaseEntity) -> None:
    """Run the post invariants after construction and raise their errors."""
    fired_codes: list[str] = []
    errors = (
        entity._run_invariants("post", return_errors=True, fired_codes=fired_codes)
        or {}
    )
    if errors:
        raise ValidationError(
            errors,
            codes=fired_codes,
            location=type(entity).__qualname__,
        )


def _collect_setattr_errors(
    entity: BaseEntity, values: dict[str, Any], errors: dict[str, list[str]]
) -> None:
    """Assign each of ``values`` to ``entity``, adding failures to ``errors``."""
    for field_name, val in values.items():
        try:
            setattr(entity, field_name, val)
        except ValidationError as err:
            # Field/setattr validation always raises the dict form of
            # ``messages`` (field name -> list of error strings).
            err_messages = cast("dict[str, list[str]]", err.messages)
            for fname in err_messages:
                errors.setdefault(fname, []).extend(err_messages[fname])


def _run_own_invariants(
    entity: BaseEntity,
    stage: str,
    errors: dict[str, list[str]],
    codes: list[str],
) -> list[str]:
    """Run ``entity``'s own invariants for ``stage`` and return the failed names.

    Each failure adds its messages to ``errors`` and its code to ``codes``.
    """
    failed_invariants: list[str] = []
    for method_name, invariant_method in entity._invariants.get(stage, {}).items():
        try:
            invariant_method(entity)
        except ValidationError as err:
            failed_invariants.append(method_name)
            codes.append(_invariant_code(invariant_method, stage))
            # Invariant failures always raise the dict form of ``messages``.
            err_messages = cast("dict[str, list[str]]", err.messages)
            for field_name in err_messages:
                errors[field_name].extend(err_messages[field_name])
    return failed_invariants


def _association_items(value: Any) -> list[Any]:
    """Return the children an association value holds, as a list."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _child_invariant_errors(
    item: BaseEntity, stage: str, codes: list[str]
) -> dict[str, list[str]] | None:
    """Run a child entity's invariants for ``stage`` and return its errors."""
    if stage == "pre":
        return item._precheck(return_errors=True, fired_codes=codes)
    return item._postcheck(return_errors=True, fired_codes=codes)


def _run_association_invariants(
    entity: BaseEntity,
    stage: str,
    errors: dict[str, list[str]],
    codes: list[str],
) -> None:
    """Run the invariants of every child in ``entity``'s associations.

    Children's errors go into ``errors`` and their codes into ``codes``.
    """
    for field_name, field_obj in declared_fields(entity).items():
        if not isinstance(field_obj, Association):
            continue
        for item in _association_items(getattr(entity, field_name)):
            item_errors = _child_invariant_errors(item, stage, codes)
            if item_errors:
                for sub_field, error_list in item_errors.items():
                    errors[sub_field].extend(error_list)


def _drops_reserved_on_replay(entity: BaseEntity, name: str) -> bool:
    """Return ``True`` when event replay must drop a write to a reserved name."""
    return bool(getattr(entity, "_replaying", False)) and name in getattr(
        type(entity).meta_, "reserved", ()
    )


def _precheck_model_field(
    entity: BaseEntity, name: str, value: Any
) -> tuple[BaseEntity, list[_EntitySnapshot]]:
    """Run the checks before a model field write and snapshot ``entity``.

    Returns the entity whose invariants guard the write (the aggregate root,
    or ``entity`` itself) and the snapshots that undo the write.
    """
    # Prevent mutation of identifier fields once set
    id_field_name = getattr(entity.__class__, _ID_FIELD_NAME, None)
    if name == id_field_name:
        existing = getattr(entity, name, None)
        if existing is not None and value != existing:
            raise InvalidOperationError("Identifiers cannot be changed once set")

    # Determine the target for invariant checks: aggregate root or self
    target = entity._root if entity._root is not None else entity

    # Status transition validation (only when invariant checks are active)
    if not target._disable_invariant_checks:
        entity._validate_status_transition(name, value)

    # Pre-check invariants
    target._precheck()

    return target, entity._snapshot_assignment(target)


def _set_descriptor_field(
    entity: BaseEntity, name: str, descriptor: Any, value: Any
) -> None:
    """Write a descriptor field through the descriptor protocol, with checks.

    The write is undone when the write or the post-check raises.
    """
    target = entity._root if entity._root is not None else entity
    target._precheck()
    if isinstance(descriptor, Association):
        snapshots = entity._snapshot_association_change(target, name, descriptor, value)
        target._add_to_open_blocks(snapshots)
    else:
        snapshots = entity._snapshot_assignment(target)
    # Association descriptors run the root's post-check inside their
    # own ``__set__``, so the write sits inside the block as well.
    with _undo_on_failure(snapshots):
        object.__setattr__(entity, name, value)
        target._postcheck()
    entity._state.mark_changed()


def _is_shadow_field_write(entity: BaseEntity, name: str) -> bool:
    """Return ``True`` when ``name`` is a shadow field set in ``model_post_init``.

    For example ``post_id`` for a ``Reference`` descriptor.
    """
    return (
        bool(getattr(entity, "_initialized", False))
        and not name.startswith("_")
        and name in entity.__dict__
    )


def _set_shadow_field(entity: BaseEntity, name: str, value: Any) -> None:
    """Write a shadow field straight into ``__dict__`` and mark ``entity`` changed.

    Writing to ``__dict__`` bypasses Pydantic's ``validate_assignment``.
    """
    entity.__dict__[name] = value  # pyright: ignore[reportIndexIssue]
    if hasattr(entity, "_state"):
        entity._state.mark_changed()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
_T = TypeVar("_T")


def entity_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
    """Factory method to create an entity class.

    This method is used to create an entity class. It is called during domain registration.
    """
    # If opts has a `limit` key and it is negative, set it to None
    if "limit" in opts and opts["limit"] is not None and opts["limit"] < 0:
        opts["limit"] = None

    # Always route to Pydantic base
    base_cls = BaseEntity

    # Derive the entity class from the base entity class
    element_cls = _derive_element_class(element_cls, base_cls, **opts)

    # ``_derive_element_class`` returns a ``BaseEntity`` subclass; narrow so the
    # entity-only surface (``meta_``, ``_invariants``, ``declared_fields``) is
    # visible to static checkers. Mirrors ``value_object_factory``.
    entity_cls = cast(type[BaseEntity], element_cls)

    if not entity_cls.meta_.part_of:
        raise IncorrectUsageError(
            f"Entity `{entity_cls.__name__}` needs to be associated with an Aggregate"
        )

    _check_part_of_kind(entity_cls)

    # Set up reference fields for entities with part_of
    if not entity_cls.meta_.abstract:
        _ensure_part_of_reference(entity_cls)
        _bind_reference_shadows(entity_cls)

    _register_invariants(entity_cls)

    return element_cls


def _reference_field_name(part_of: Any) -> str:
    """Return the name of the auto-generated ``Reference`` to ``part_of``.

    ``part_of`` is a class or a class name.
    """
    if isinstance(part_of, str):
        return inflection.underscore(part_of)
    return inflection.underscore(part_of.__name__)


def _ensure_part_of_reference(entity_cls: type[BaseEntity]) -> None:
    """Add a ``Reference`` to the ``part_of`` element unless one is declared."""
    if any(
        isinstance(field_obj, Reference)
        for field_obj in declared_fields(entity_cls).values()
    ):
        return

    reference_field = Reference(entity_cls.meta_.part_of)
    reference_field._auto_generated = True

    field_name = _reference_field_name(entity_cls.meta_.part_of)
    setattr(entity_cls, field_name, reference_field)

    # Set the name of the field on itself
    reference_field.__set_name__(entity_cls, field_name)

    field_objects = getattr(entity_cls, _FIELDS)
    field_objects[field_name] = reference_field
    setattr(entity_cls, _FIELDS, field_objects)


def _bind_reference_shadows(entity_cls: type[BaseEntity]) -> None:
    """Bind the shadow field of each ``Reference`` field to ``entity_cls``."""
    for field_obj in getattr(entity_cls, _FIELDS, {}).values():
        if isinstance(field_obj, Reference):
            shadow_field_name, shadow_field = field_obj.get_shadow_field()
            if shadow_field_name is not None:
                shadow_field.__set_name__(entity_cls, shadow_field_name)


def _register_invariants(entity_cls: type[BaseEntity]) -> None:
    """Record the methods marked ``@invariant`` across ``entity_cls``'s MRO."""
    for klass in entity_cls.__mro__:
        for method_name, method in vars(klass).items():
            if (
                not (method_name.startswith("__") and method_name.endswith("__"))
                and callable(method)
                and hasattr(method, "_invariant")
            ):
                entity_cls._invariants[method._invariant][method_name] = method


_INVARIANT_STAGE_CODES: dict[str, DiagnosticCode] = {
    "pre": DiagnosticCode.INVARIANT_PRE_FAILED,
    "post": DiagnosticCode.INVARIANT_POST_FAILED,
}


def _invariant_code(method: Callable[..., Any], stage: str) -> str:
    """The diagnostic code for a fired invariant: the author's ``code=`` when
    the invariant declared one, else the framework default for the stage."""
    custom = getattr(method, "_invariant_code", None)
    if custom is not None:
        return str(custom)
    return _INVARIANT_STAGE_CODES[stage].value


def _mark_invariant(
    func: Callable[..., Any], stage: str, code: DiagnosticCode | str | None
) -> Callable[..., Any]:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    setattr(wrapper, "_invariant", stage)
    # An empty code is treated as none given, so a falsy string falls back to the
    # stage default instead of masquerading as a real code.
    if code:
        setattr(wrapper, "_invariant_code", code)
    return wrapper


class invariant:
    @staticmethod
    def pre(
        func: Callable[..., Any] | None = None,
        *,
        code: DiagnosticCode | str | None = None,
    ) -> Callable[..., Any]:
        """Mark a method as a pre-condition invariant.

        Use bare as ``@invariant.pre``, or pass ``code`` to stamp a specific
        diagnostic code on the failure: ``@invariant.pre(code=...)``. Without
        it, an aggregate, entity, or domain-service failure carries the default
        ``INVARIANT_PRE_FAILED``.
        """

        def decorate(f: Callable[..., Any]) -> Callable[..., Any]:
            return _mark_invariant(f, "pre", code)

        return decorate(func) if func is not None else decorate

    @staticmethod
    def post(
        func: Callable[..., Any] | None = None,
        *,
        code: DiagnosticCode | str | None = None,
    ) -> Callable[..., Any]:
        """Mark a method as a post-condition invariant.

        Use bare as ``@invariant.post``, or pass ``code`` to stamp a specific
        diagnostic code on the failure: ``@invariant.post(code=...)``. Without
        it, an aggregate, entity, or domain-service failure carries the default
        ``INVARIANT_POST_FAILED``, and a value object carries
        ``VALUE_OBJECT_INVARIANT_FAILED``.
        """

        def decorate(f: Callable[..., Any]) -> Callable[..., Any]:
            return _mark_invariant(f, "post", code)

        return decorate(func) if func is not None else decorate
