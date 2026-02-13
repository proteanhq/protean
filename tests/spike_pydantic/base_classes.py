"""Pydantic-native base classes for Protean domain elements.

This is a proof-of-concept spike to validate the full Pydantic native approach
before committing to the migration.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, ClassVar, Generic, TypeVar, get_origin

from pydantic import BaseModel, ConfigDict, PrivateAttr

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Entity State Tracking
# ---------------------------------------------------------------------------
class _EntityState:
    """Track lifecycle state of an entity: new, changed, destroyed."""

    def __init__(self) -> None:
        self._new = True
        self._changed = False
        self._destroyed = False

    @property
    def is_new(self) -> bool:
        return self._new

    @property
    def is_changed(self) -> bool:
        return self._changed

    @property
    def is_persisted(self) -> bool:
        return not self._new

    @property
    def is_destroyed(self) -> bool:
        return self._destroyed

    def mark_new(self) -> None:
        self._new = True

    def mark_saved(self) -> None:
        self._new = False
        self._changed = False

    def mark_changed(self) -> None:
        self._changed = True

    def mark_destroyed(self) -> None:
        self._destroyed = True


# ---------------------------------------------------------------------------
# Options (metadata) - kept orthogonal to Pydantic
# ---------------------------------------------------------------------------
class Options(dict):
    """Metadata info for domain elements (meta_)."""

    def __init__(self, opts: dict | None = None) -> None:
        super().__init__()
        if opts:
            self.update(opts)
        self.setdefault("abstract", False)

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'Options' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


# ---------------------------------------------------------------------------
# Association Markers (HasOne / HasMany)
# ---------------------------------------------------------------------------
class _AssociationMarker:
    """Base marker for association fields. Detected during __init_subclass__
    and transformed into PrivateAttr + property."""

    pass


class HasMany(Generic[T], _AssociationMarker):
    """Marker for one-to-many association. Usage: items: HasMany[OrderItem]"""

    pass


class HasOne(Generic[T], _AssociationMarker):
    """Marker for one-to-one association. Usage: address: HasOne[ShippingInfo]"""

    pass


# ---------------------------------------------------------------------------
# Invariant Decorator
# ---------------------------------------------------------------------------
class _InvariantDecorator:
    """Decorator for marking methods as invariant checks."""

    def __init__(self, stage: str) -> None:
        self.stage = stage

    def __call__(self, fn):
        fn._invariant = self.stage
        return fn


class invariant:
    pre = _InvariantDecorator("pre")
    post = _InvariantDecorator("post")


# ---------------------------------------------------------------------------
# Protean Value Object
# ---------------------------------------------------------------------------
class ProteanValueObject(BaseModel):
    """Base class for Value Objects - immutable, no identity, equality by value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # meta_ is set by the domain decorator or directly
    _meta: Options = PrivateAttr(default_factory=Options)
    _invariants: dict = PrivateAttr(default_factory=lambda: defaultdict(dict))

    def model_post_init(self, __context: Any) -> None:
        # Discover and run post-invariants
        self._discover_invariants()
        errors = self._run_invariants("post")
        if errors:
            from protean.exceptions import ValidationError

            raise ValidationError(errors)

    def _discover_invariants(self) -> None:
        """Scan class MRO for @invariant decorated methods."""
        for cls in type(self).__mro__:
            for name, attr in vars(cls).items():
                if callable(attr) and hasattr(attr, "_invariant"):
                    bound = getattr(self, name)
                    self._invariants[attr._invariant][name] = bound

    def _run_invariants(self, stage: str) -> dict:
        """Run invariants for a given stage. Return errors dict or empty."""
        errors: dict[str, list] = defaultdict(list)
        for method in self._invariants.get(stage, {}).values():
            try:
                method()
            except Exception as err:
                if hasattr(err, "messages"):
                    for field_name, msgs in err.messages.items():
                        errors[field_name].extend(msgs)
                else:
                    errors["_entity"].append(str(err))
        return dict(errors) if errors else {}


# ---------------------------------------------------------------------------
# Association Detection Helper
# ---------------------------------------------------------------------------
def _detect_association_marker(annotation: Any) -> type | None:
    """Detect if an annotation is a HasMany[T] or HasOne[T] marker.

    Handles both resolved types and string annotations (from `__future__`).
    Returns the marker class (HasMany or HasOne) or None.
    """
    # Handle string annotations (from __future__ import annotations)
    if isinstance(annotation, str):
        if annotation.startswith("HasMany[") or annotation == "HasMany":
            return HasMany
        if annotation.startswith("HasOne[") or annotation == "HasOne":
            return HasOne
        return None

    # Handle resolved type annotations
    origin = get_origin(annotation)
    if origin is not None:
        try:
            if issubclass(origin, _AssociationMarker):
                return origin
        except TypeError:
            pass

    return None


# ---------------------------------------------------------------------------
# Protean Entity
# ---------------------------------------------------------------------------
class ProteanEntity(BaseModel):
    """Base class for Entities - mutable, with identity, part of aggregate."""

    model_config = ConfigDict(
        validate_assignment=True,
        extra="forbid",
        arbitrary_types_allowed=True,
    )

    _state: _EntityState = PrivateAttr(default_factory=_EntityState)
    _root: Any = PrivateAttr(default=None)
    _owner: Any = PrivateAttr(default=None)
    _initialized: bool = PrivateAttr(default=False)
    _invariants: dict = PrivateAttr(default_factory=lambda: defaultdict(dict))
    _meta: Options = PrivateAttr(default_factory=Options)

    # Association storage
    _associations: dict = PrivateAttr(default_factory=dict)
    _temp_cache: dict = PrivateAttr(
        default_factory=lambda: defaultdict(lambda: defaultdict(dict))
    )

    # Class-level registry of association declarations (populated by __init_subclass__)
    _association_decls: ClassVar[dict] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Strip HasMany[T]/HasOne[T] annotations before Pydantic processes them.

        Pydantic's ModelMetaclass reads __annotations__ to create model fields.
        We must intercept association markers and remove them from annotations
        BEFORE Pydantic sees them. Store the info in a class-level dict for
        later initialization in model_post_init.

        Note: With `from __future__ import annotations`, annotations are strings.
        We handle both string and resolved annotation forms.
        """
        super().__init_subclass__(**kwargs)

        # Collect association declarations from THIS class's own annotations
        own_annotations = cls.__dict__.get("__annotations__", {})
        assoc_decls: dict[str, type] = {}

        for field_name, annotation in list(own_annotations.items()):
            marker = _detect_association_marker(annotation)
            if marker is not None:
                assoc_decls[field_name] = marker
                # Remove from __annotations__ so Pydantic doesn't process it
                del own_annotations[field_name]

        # Merge with parent association declarations
        parent_decls = {}
        for base in cls.__mro__[1:]:
            pd = getattr(base, "_association_decls", None)
            if isinstance(pd, dict) and pd:
                parent_decls.update(pd)

        if assoc_decls or parent_decls:
            cls._association_decls = {**parent_decls, **assoc_decls}

    def model_post_init(self, __context: Any) -> None:
        self._discover_invariants()
        self._setup_associations()
        # Run post-invariants after init
        errors = self._run_invariants("post")
        if errors:
            from protean.exceptions import ValidationError

            raise ValidationError(errors)
        self._initialized = True

    def _discover_invariants(self) -> None:
        """Scan class MRO for @invariant decorated methods."""
        for cls in type(self).__mro__:
            for name, attr in vars(cls).items():
                if callable(attr) and hasattr(attr, "_invariant"):
                    bound = getattr(self, name)
                    self._invariants[attr._invariant][name] = bound

    def _setup_associations(self) -> None:
        """Initialize association storage from class-level _association_decls."""
        for field_name, marker_type in self.__class__._association_decls.items():
            if issubclass(marker_type, HasMany):
                self._associations[field_name] = []
            elif issubclass(marker_type, HasOne):
                self._associations[field_name] = None

    def _run_invariants(self, stage: str) -> dict:
        errors: dict[str, list] = defaultdict(list)
        for method in self._invariants.get(stage, {}).values():
            try:
                method()
            except Exception as err:
                if hasattr(err, "messages"):
                    for field_name, msgs in err.messages.items():
                        errors[field_name].extend(msgs)
                else:
                    errors["_entity"].append(str(err))
        return dict(errors) if errors else {}

    def _precheck(self) -> None:
        errors = self._run_invariants("pre")
        if errors:
            from protean.exceptions import ValidationError

            raise ValidationError(errors)

    def _postcheck(self) -> None:
        errors = self._run_invariants("post")
        if errors:
            from protean.exceptions import ValidationError

            raise ValidationError(errors)

    def __setattr__(self, name: str, value: Any) -> None:
        # For Pydantic model fields, wrap with invariant checks and state tracking
        if name in self.__class__.model_fields and self._initialized:
            # Pre-check invariants
            root = self._root
            if root is not None:
                root._precheck()

            # Pydantic validation + assignment
            super().__setattr__(name, value)

            # Post-check invariants
            if root is not None:
                root._postcheck()

            # Mark as changed
            self._state.mark_changed()
        else:
            super().__setattr__(name, value)

    def __getattr__(self, name: str) -> Any:
        """Intercept access to association fields stored in _associations."""
        # PrivateAttr access is handled by Pydantic's __getattr__
        # We intercept association field names
        try:
            private = object.__getattribute__(self, "__pydantic_private__")
            if private and "_associations" in private:
                associations = private["_associations"]
                if name in associations:
                    return associations[name]
        except AttributeError:
            pass
        # Fall back to Pydantic's __getattr__
        return super().__getattr__(name)

    def __eq__(self, other: object) -> bool:
        """Equality based on identity (id field)."""
        if type(other) is type(self):
            return self.id == other.id
        return False

    def __hash__(self) -> int:
        return hash(self.id)


# ---------------------------------------------------------------------------
# Protean Aggregate
# ---------------------------------------------------------------------------
class ProteanAggregate(ProteanEntity):
    """Base class for Aggregates - root entity with versioning and events."""

    _version: int = PrivateAttr(default=-1)
    _next_version: int = PrivateAttr(default=0)
    _events: list = PrivateAttr(default_factory=list)
    _event_position: int = PrivateAttr(default=0)

    def model_post_init(self, __context: Any) -> None:
        # Set self as root
        self._root = self
        self._owner = self
        super().model_post_init(__context)

    def raise_(self, event: Any) -> None:
        """Raise a domain event."""
        self._events.append(event)


# ---------------------------------------------------------------------------
# Protean Command
# ---------------------------------------------------------------------------
class ProteanCommand(BaseModel):
    """Base class for Commands - immutable intent to change state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _metadata: dict = PrivateAttr(default_factory=dict)
    _meta: Options = PrivateAttr(default_factory=Options)

    def model_post_init(self, __context: Any) -> None:
        # Build metadata after field validation
        self._metadata = {
            "kind": "COMMAND",
            "type": self.__class__.__name__,
        }

    @property
    def payload(self) -> dict:
        """Return field data without metadata."""
        return self.model_dump()


# ---------------------------------------------------------------------------
# Protean Event
# ---------------------------------------------------------------------------
class ProteanEvent(BaseModel):
    """Base class for Events - immutable facts about what happened."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _metadata: dict = PrivateAttr(default_factory=dict)
    _meta: Options = PrivateAttr(default_factory=Options)

    def model_post_init(self, __context: Any) -> None:
        self._metadata = {
            "kind": "EVENT",
            "type": self.__class__.__name__,
        }

    @property
    def payload(self) -> dict:
        """Return field data without metadata."""
        return self.model_dump()


# ---------------------------------------------------------------------------
# Protean Projection
# ---------------------------------------------------------------------------
class ProteanProjection(BaseModel):
    """Base class for Projections - mutable read models."""

    model_config = ConfigDict(
        validate_assignment=True,
        extra="forbid",
    )

    _state: _EntityState = PrivateAttr(default_factory=_EntityState)
    _meta: Options = PrivateAttr(default_factory=Options)
