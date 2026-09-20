"""FieldSpec: the domain-native field declaration carrier.

A FieldSpec is a plain data object that carries type information and constraints.
It is consumed during class creation and translated into Pydantic-compatible
``Annotated[type, Field(...)]`` annotations.  After the metaclass runs, only
Pydantic's native machinery remains; FieldSpec itself is not stored on the class.
"""

import contextlib
import datetime as _dt
import decimal
import warnings
from collections.abc import Callable, Iterable
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import AfterValidator, BeforeValidator
from pydantic import Field as PydanticField

from protean.exceptions import ConfigurationError
from protean.exceptions import ValidationError as ProteanValidationError
from protean.fields.base import (
    EMPTY_VALUES,
    normalize_field_renamed_from,
)
from protean.ir.diagnostics import DiagnosticCode
from protean.utils import (
    FALSY_FLAG_SPELLINGS,
    TRUTHY_FLAG_SPELLINGS,
    _generate_identity,
    _normalize_deprecated,
)
from protean.utils.globals import current_domain


# ---------------------------------------------------------------------------
# Sentinel for "no default provided"
# ---------------------------------------------------------------------------
class _UNSET_TYPE:
    """Sentinel indicating no default was provided."""

    _instance: "_UNSET_TYPE | None" = None

    def __new__(cls) -> "_UNSET_TYPE":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


_UNSET = _UNSET_TYPE()


# ---------------------------------------------------------------------------
# FieldSpec
# ---------------------------------------------------------------------------
class FieldSpec:
    """Domain-native field declaration carrier.

    A FieldSpec records the user's intent (``String(max_length=50)``) and
    translates it into a Pydantic ``Annotated[type, Field(...)]`` during
    class creation.  It is **not** a descriptor (it has no ``__get__`` or
    ``__set__``) and is discarded after the class is built.
    """

    # Auto()-specific metadata, set on the instance by the ``Auto`` factory
    # (see ``protean.fields.simple``) and read back here via ``getattr`` with
    # a default.  Declared for static checkers; not initialized in ``__init__``.
    _increment: bool
    _identity_strategy: str | None
    _identity_function: Callable[..., Any] | str | None
    _identity_type: str | None
    # Set by the ``List`` factory when the deprecated ``pickled=`` argument is
    # passed, so ``protean check`` can surface the usage. Read via ``getattr``
    # with a ``False`` default; absent on every other spec.
    _pickled_deprecated: bool
    # The custom type's Pydantic validators and serializers, set by the
    # ``Custom`` factory. ``resolve_type`` attaches them to the annotation;
    # keeping them off ``python_type`` leaves the base type visible to the
    # type-specific constraint resolution. Read via ``getattr`` with an empty
    # default; absent on every other spec.
    _custom_metadata: tuple[Any, ...]

    def __init__(
        self,
        python_type: type,
        *,
        # Field kind marker (for adapter-layer discrimination)
        field_kind: str = "standard",  # "standard", "text", "identifier", "auto"
        # Common arguments
        required: bool = False,
        default: Any = _UNSET,
        identifier: bool = False,
        unique: bool = False,
        choices: type[Enum]
        | list[Any]
        | tuple[Any, ...]
        | None = None,  # supports Enum classes too
        description: str = "",
        referenced_as: str | None = None,
        # Type-specific constraints
        max_length: int | None = None,
        min_length: int | None = None,
        max_value: float | int | decimal.Decimal | None = None,
        min_value: float | int | decimal.Decimal | None = None,
        # Decimal-specific (NUMERIC(precision, scale))
        precision: int | None = None,
        scale: int | None = None,
        # Container-specific
        content_type: Any = None,  # For List fields
        # Sanitization — tri-state for String/Text: True (always clean),
        # False (never), None (unset → consult the domain-level
        # ``[field_defaults] sanitize`` default, which itself defaults to
        # False). Other field kinds never expose this and stay unset.
        sanitize: bool | None = None,  # For String/Text — runs bleach.clean()
        # Lifecycle timestamps (DateTime/Date only) — Django-parity flags that
        # let the persistence layer stamp the field on save.
        auto_now_add: bool = False,  # set to now() on the CREATE save
        auto_now: bool = False,  # set to now() on every save (create + update)
        # Validators
        validators: Iterable[Callable[..., Any]] = (),  # Per-field validator callables
        # Error messages
        error_messages: dict[str, str] | None = None,
        # Status transitions
        transitions: dict[Any, Any]
        | None = None,  # For Status fields — {state: [allowed_targets]}
        # Deprecation metadata
        deprecated: str | dict[str, Any] | None = None,
        # Old field name(s) this field was renamed from
        renamed_from: str | list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.python_type = python_type
        self.field_kind = field_kind
        self.required = required
        self.default = default
        self.identifier = identifier
        self.unique = unique
        self.choices = choices
        self.description = description
        self.referenced_as = referenced_as
        self.max_length = max_length
        self.min_length = min_length
        self.max_value = max_value
        self.min_value = min_value
        self.precision = precision
        self.scale = scale
        self.content_type = content_type
        self.sanitize = sanitize
        self.auto_now_add = auto_now_add
        self.auto_now = auto_now
        self.validators = list(validators)
        self.error_messages = error_messages
        self.transitions = (
            self._normalize_transitions(transitions) if transitions else None
        )
        self._auto_generated = False
        self.deprecated = _normalize_deprecated(deprecated)
        self.renamed_from = normalize_field_renamed_from(renamed_from)

        # Warn if required=True with an explicit default
        if self.required and self.default is not _UNSET:
            warnings.warn(
                "Field declared with required=True and an explicit default. "
                "The default will be honored; the field is effectively not required.",
                stacklevel=3,
            )

        # auto_now / auto_now_add are Django-parity, save-time stamps and only
        # apply to temporal fields. They are mutually exclusive.
        if self.auto_now or self.auto_now_add:
            if self.python_type not in (_dt.datetime, _dt.date):
                raise ProteanValidationError(
                    {
                        "auto_now": [
                            "auto_now/auto_now_add are only supported on "
                            "DateTime and Date fields"
                        ]
                    }
                )
            if self.auto_now and self.auto_now_add:
                raise ProteanValidationError(
                    {
                        "auto_now": [
                            "auto_now and auto_now_add are mutually exclusive: "
                            "auto_now stamps on every save, auto_now_add only on "
                            "create"
                        ]
                    }
                )
            if self.required:
                raise ProteanValidationError(
                    {
                        "auto_now": [
                            "auto_now/auto_now_add fields cannot be required: the "
                            "value is stamped at save time, so the field must be "
                            "optional (drop required=True)"
                        ]
                    }
                )

    # ------------------------------------------------------------------
    # Resolution methods
    # ------------------------------------------------------------------
    def resolve_type(self) -> Any:
        """Return the Python type annotation for Pydantic.

        Handles choices → Literal, and optional wrapping.
        """
        resolved: Any = self.python_type

        # If choices is set, replace with Literal
        if self.choices is not None:
            if isinstance(self.choices, type) and issubclass(self.choices, Enum):
                choices_values = tuple(item.value for item in self.choices)
            else:
                choices_values = tuple(self.choices)
            resolved = Literal[choices_values]

        # A custom field carries its type's validators and serializers on the
        # spec; attach them here so Pydantic gets a type it can parse.
        custom_metadata = getattr(self, "_custom_metadata", ())
        if custom_metadata:
            resolved = Annotated[(resolved, *custom_metadata)]

        # Wrap in Optional when not required, no explicit default, and not identifier.
        # Auto-increment identifiers are also Optional since the DAO assigns
        # the actual integer value at persistence time.
        is_increment_id = self.identifier and getattr(self, "_increment", False)
        if (
            not self.required
            and self.default is _UNSET
            and (not self.identifier or is_increment_id)
        ):
            resolved = resolved | None

        return resolved

    def resolve_field_kwargs(self) -> dict[str, Any]:
        """Return the kwargs dict for ``pydantic.Field(...)``."""
        kwargs: dict[str, Any] = {}
        json_extra: dict[str, Any] = {}

        # String-type constraints (only for str-based types)
        if isinstance(self.python_type, type) and issubclass(self.python_type, str):
            if self.max_length is not None:
                kwargs["max_length"] = self.max_length
            if self.min_length is not None:
                kwargs["min_length"] = self.min_length
            # required=True on string fields means non-empty
            if self.required and self.min_length is None:
                kwargs["min_length"] = 1

        # Numeric constraints
        if self.max_value is not None:
            kwargs["le"] = self.max_value
        if self.min_value is not None:
            kwargs["ge"] = self.min_value

        # Decimal precision/scale → Pydantic validation + adapter metadata
        # (read back by ResolvedField for the SQLAlchemy NUMERIC(p, s) mapping).
        if self.python_type is decimal.Decimal:
            if self.precision is not None:
                kwargs["max_digits"] = self.precision
                json_extra["precision"] = self.precision
            if self.scale is not None:
                kwargs["decimal_places"] = self.scale
                json_extra["scale"] = self.scale

        # Handle identifier
        if self.identifier:
            json_extra["identifier"] = True
            if self.default is _UNSET:
                if getattr(self, "_increment", False):
                    # Auto-increment identifiers: the DAO handles the
                    # actual value generation; default to None here.
                    kwargs["default"] = None
                elif self.field_kind in ("identifier", "auto"):
                    # Use _generate_identity with identity_* options from Auto()
                    _id_strategy = getattr(self, "_identity_strategy", None)
                    _id_function = getattr(self, "_identity_function", None)
                    _id_type = getattr(self, "_identity_type", None)

                    kwargs["default_factory"] = (
                        lambda s=_id_strategy, f=_id_function, t=_id_type: (
                            _generate_identity(
                                identity_strategy=s,
                                identity_function=f,
                                identity_type=t,
                            )
                        )
                    )
                    # Ensure the default_factory result is validated so
                    # that BeforeValidator(_coerce_to_str) can coerce
                    # UUID objects to str for identity fields.
                    kwargs["validate_default"] = True

        # For non-identifier Auto fields, auto-generate UUIDs unless increment
        if (
            not self.identifier
            and self.field_kind == "auto"
            and self.default is _UNSET
            and not getattr(self, "_increment", False)
        ):
            kwargs["default_factory"] = lambda: str(uuid4())

        # Handle default
        if self.default is not _UNSET:
            if callable(self.default):
                kwargs["default_factory"] = self.default
            elif isinstance(self.default, (list, dict)):
                # Prevent mutable default bug
                kwargs["default_factory"] = lambda d=self.default: type(d)(d)
            else:
                kwargs["default"] = self.default
        elif (
            not self.required
            and not self.identifier
            and "default_factory" not in kwargs
        ):
            kwargs["default"] = None

        # Description
        if self.description:
            kwargs["description"] = self.description

        # Collect Protean-only metadata into json_schema_extra
        if self.unique:
            json_extra["unique"] = True
        if self.referenced_as:
            json_extra["referenced_as"] = self.referenced_as
        if self.field_kind != "standard":
            json_extra["field_kind"] = self.field_kind
        # Only an explicit ``sanitize=True`` is recorded in the IR: it is the
        # declared intent. An unset field (the new default) carries no marker,
        # because whether it sanitizes depends on the domain default resolved at
        # validation time, not on anything the field declares.
        if self.sanitize is True:
            json_extra["sanitize"] = True
        if self.auto_now:
            json_extra["auto_now"] = True
        if self.auto_now_add:
            json_extra["auto_now_add"] = True
        if getattr(self, "_increment", False):
            json_extra["increment"] = True
        if self.validators:
            json_extra["_validators"] = list(self.validators)
        if self.error_messages:
            json_extra["_error_messages"] = self.error_messages
        if self._auto_generated:
            json_extra["_auto_generated"] = True
        if self.transitions is not None:
            json_extra["transitions"] = self.transitions
        if self.deprecated is not None:
            json_extra["_deprecated"] = self.deprecated

        if self.renamed_from is not None:
            json_extra["_renamed_from"] = self.renamed_from

        if json_extra:
            kwargs["json_schema_extra"] = json_extra

        return kwargs

    def resolve_annotated(self) -> Any:
        """Combine resolved type and field kwargs into ``Annotated[type, Field(...)]``.

        Per-field ``validators`` are appended as ``AfterValidator`` wrappers on
        the ``Annotated`` metadata. A sanitization ``AfterValidator`` is appended
        for an explicit ``sanitize=True`` *and* for a String/Text field that
        leaves ``sanitize`` unset: the unset field cannot decide at build time
        whether it sanitizes, because that depends on the domain-level
        ``[field_defaults] sanitize`` default, which is only known at validation
        time. So the unset field carries the validator and the validator returns
        the value untouched when the domain default is off. Only an explicit
        ``sanitize=False`` gets no validator at all.
        """
        resolved_type = self.resolve_type()
        field_kwargs = self.resolve_field_kwargs()
        pydantic_field = PydanticField(**field_kwargs)

        extra_validators: list[Any] = []

        # Coerce non-str values (e.g. int, UUID) to str for identifier
        # and auto fields.  The old field system did this automatically;
        # Pydantic v2 strict mode rejects them otherwise.
        # Applies when:
        #   - The field is marked as identifier=True, OR
        #   - The field_kind is "identifier" or "auto" (e.g. Identifier()
        #     used as a reference, not just as the entity's identity)
        # Excludes Auto(increment=True) fields that store integer sequences.
        if self.python_type is str and (
            self.identifier or self.field_kind in ("identifier", "auto")
        ):
            extra_validators.append(BeforeValidator(_coerce_to_str))

        # Sanitization via AfterValidator. The field's length bounds are
        # re-enforced on the sanitized (stored) value so a value that passes on
        # write always round-trips through serialization and replay — bleach can
        # otherwise store a value out of bounds (escaping grows it, comment /
        # attribute stripping shrinks it). ``choices`` fields are never sanitized:
        # the value must match a declared choice exactly, and HTML-escaping a
        # closed vocabulary would break that match. See ADR-0026.
        #
        # The framework default is now ``sanitize=False``: a String/Text
        # field left unset does not sanitize unless a domain turns it on via
        # ``[field_defaults] sanitize = true``. So the validator is attached
        # whenever ``sanitize`` is not explicitly False (explicit True, or unset
        # on a String/Text field), and it decides at call time whether to clean:
        #   - explicit True  → always cleans (``always=True``)
        #   - unset (None)   → cleans only when the active domain's field default
        #                      is True (``always=False``); with no active domain
        #                      it falls back to the framework default and does not
        #                      clean.
        # Explicit False attaches no validator, so a raw field keeps its
        # raw-input length behavior and pays no per-value cost.
        sanitize_applies = self.sanitize is True or (
            self.sanitize is None and self.field_kind in ("standard", "text")
        )
        if (
            sanitize_applies
            and self.choices is None
            and isinstance(self.python_type, type)
            and issubclass(self.python_type, str)
        ):
            # Mirror the effective ``min_length`` from ``resolve_field_kwargs``:
            # a required string has an implicit lower bound of 1.
            effective_min_length = self.min_length
            if effective_min_length is None and self.required:
                effective_min_length = 1
            extra_validators.append(
                AfterValidator(
                    _make_sanitize_validator(
                        effective_min_length,
                        self.max_length,
                        always=self.sanitize is True,
                    )
                )
            )

        # Per-field validators via AfterValidator
        if self.validators:
            captured_validators = list(self.validators)

            def _run_protean_validators(
                v: Any,
                validators: list[Callable[..., Any]] = captured_validators,
            ) -> Any:
                # Skip validators for empty values, matching the legacy field
                # system and the documented order (empty -> choices -> cast ->
                # validators). An optional field left unset arrives here as None
                # and must not be validated.
                if v in EMPTY_VALUES:
                    return v
                for validator_fn in validators:
                    try:
                        validator_fn(v)
                    except ProteanValidationError as e:
                        # Re-raise as ValueError so Pydantic catches it and
                        # maps it to the correct field name.
                        msg = str(e.messages) if hasattr(e, "messages") else str(e)
                        # If the validator set an error string on itself, use that
                        msg = getattr(validator_fn, "error", msg)
                        raise ValueError(msg) from e
                return v

            extra_validators.append(AfterValidator(_run_protean_validators))

        if extra_validators:
            return Annotated[
                resolved_type,
                pydantic_field,
                *extra_validators,
            ]
        return Annotated[resolved_type, pydantic_field]

    @staticmethod
    def _normalize_transitions(
        transitions: dict[Any, Any],
    ) -> dict[str, list[str]]:
        """Normalize Enum members in a transition map to string values.

        Accepts both Enum members and raw strings as keys/values::

            {OrderStatus.DRAFT: [OrderStatus.PLACED, OrderStatus.CANCELLED]}
            # becomes
            {"DRAFT": ["PLACED", "CANCELLED"]}
        """
        normalized: dict[str, list[str]] = {}
        for source, targets in transitions.items():
            key = source.value if isinstance(source, Enum) else str(source)
            normalized[key] = [
                t.value if isinstance(t, Enum) else str(t) for t in targets
            ]
        return normalized

    def __repr__(self) -> str:
        # Map (python_type, field_kind) to user-friendly factory name
        _FACTORY_NAMES: dict[tuple[type, str], str] = {
            (str, "standard"): "String",
            (str, "text"): "Text",
            (str, "identifier"): "Identifier",
            (str, "status"): "Status",
            (str, "auto"): "Auto",
            (int, "auto"): "Auto",
            (int, "standard"): "Integer",
            (float, "standard"): "Float",
            (decimal.Decimal, "standard"): "Decimal",
            (bool, "standard"): "Boolean",
        }

        base_type = self.python_type
        # For container types (list[X], dict), extract the origin
        origin = getattr(base_type, "__origin__", None)
        if origin is list:
            factory_name = "List"
        elif origin is dict or base_type is dict:
            factory_name = "Dict"
        elif base_type is _dt.date:
            factory_name = "Date"
        elif base_type is _dt.datetime:
            factory_name = "DateTime"
        else:
            factory_name = _FACTORY_NAMES.get((base_type, self.field_kind), "FieldSpec")

        parts: list[str] = []
        if self.description:
            parts.append(f"description={self.description!r}")
        if self.identifier:
            parts.append("identifier=True")
        if not self.identifier and self.required:
            parts.append("required=True")
        if self.referenced_as:
            parts.append(f"referenced_as={self.referenced_as!r}")
        if self.default is not _UNSET:
            if callable(self.default):
                parts.append(f"default={self.default.__name__}")
            elif isinstance(self.default, str):
                parts.append(f"default={self.default!r}")
            else:
                parts.append(f"default={self.default!r}")
        if self.max_length is not None:
            parts.append(f"max_length={self.max_length}")
        if self.min_length is not None:
            parts.append(f"min_length={self.min_length}")
        if self.max_value is not None:
            parts.append(f"max_value={self.max_value}")
        if self.min_value is not None:
            parts.append(f"min_value={self.min_value}")
        # Show sanitize only when it deviates from the factory default, which is
        # now unset (``None``). Both explicit values deviate, and they are no
        # longer interchangeable: under ``[field_defaults] sanitize = true`` an
        # unset field cleans while an explicit ``sanitize=False`` stays raw, so
        # hiding the False would make a per-field opt-out invisible.
        if factory_name in ("String", "Text") and self.sanitize is not None:
            parts.append(f"sanitize={self.sanitize}")
        # Show increment for Auto fields
        if factory_name == "Auto" and getattr(self, "_increment", False):
            parts.append("increment=True")
        # Show transition count for Status fields
        if factory_name == "Status" and self.transitions:
            n_rules = sum(len(v) for v in self.transitions.values())
            parts.append(f"transitions=<{n_rules} rules>")
        return f"{factory_name}({', '.join(parts)})"


# ---------------------------------------------------------------------------
# Class creation helper — shared by all base classes
# ---------------------------------------------------------------------------
def resolve_fieldspecs(cls: type) -> None:
    """Transform FieldSpec declarations into Pydantic-compatible annotations.

    Called from ``__init_subclass__`` in each domain element base class
    (BaseEntity, BaseValueObject, BaseMessageType, BaseProjection).

    Handles two declaration styles:
    - Assignment: ``name = String(max_length=50)``  → FieldSpec in ``vars(cls)``
    - Annotation: ``name: String(max_length=50)``   → FieldSpec in ``cls.__annotations__``
    """
    own_annots = getattr(cls, "__annotations__", {})
    resolved_annots = dict(own_annots)

    # Track original FieldSpecs for downstream metadata access
    field_meta: dict[str, FieldSpec] = {}

    # 1. Scan class namespace for assignment-style FieldSpecs
    names_to_remove: list[str] = []
    for name, value in list(vars(cls).items()):
        if isinstance(value, FieldSpec):
            resolved_annots[name] = value.resolve_annotated()
            field_meta[name] = value
            names_to_remove.append(name)

    # Remove FieldSpec objects from namespace so Pydantic doesn't see them
    for name in names_to_remove:
        with contextlib.suppress(AttributeError):
            delattr(cls, name)

    # 2. Scan annotations for annotation-style FieldSpecs
    for name, annot_value in list(own_annots.items()):
        if isinstance(annot_value, FieldSpec):
            if name in field_meta:
                # Assignment took precedence; skip annotation duplicate
                warnings.warn(
                    f"Field '{name}' declared in both assignment and annotation "
                    f"style. Using assignment style.",
                    stacklevel=2,
                )
                continue
            resolved_annots[name] = annot_value.resolve_annotated()
            field_meta[name] = annot_value

    cls.__annotations__ = resolved_annots

    # Store FieldSpec metadata for downstream access (adapters, reflection)
    if field_meta:
        existing: dict[str, FieldSpec] = getattr(cls, "__protean_field_meta__", {})
        setattr(cls, "__protean_field_meta__", {**existing, **field_meta})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _coerce_to_str(v: Any) -> str:
    """Coerce a value to ``str`` for identifier/auto fields.

    The old Protean field system automatically coerced ``int``, ``UUID``,
    etc. to ``str``.  This ``BeforeValidator`` restores that behavior
    under Pydantic v2's strict validation.
    """
    if v is None:
        return v  # type: ignore[return-value]
    return str(v)


def _sanitize_string(v: str) -> str:
    """Sanitise a string value using bleach (if available)."""
    if not isinstance(v, str):
        return v
    try:
        import bleach  # type: ignore[import-untyped]  # noqa: PLC0415

        cleaned: str = bleach.clean(v)
        return cleaned
    except ImportError:
        return v


def _domain_default_sanitize() -> bool:
    """The active domain's ``[field_defaults] sanitize`` default.

    Read at validation time, because a field is baked into a Pydantic
    annotation before it is registered with any domain, so the domain default
    is not known when the field is built. With no active domain (a value object
    or entity constructed outside a domain context, as several tests do), there
    is no default to read, so this returns the framework default (``False``):
    do not sanitize. A missing ``field_defaults``/``sanitize`` key reads the
    same way.

    Only a *missing* key falls back. A malformed section is rejected at config
    load time by ``Config2._validate_field_defaults``, so it never reaches here;
    if one does (a config mutated in place after load), the resulting
    ``TypeError`` propagates rather than being read as "do not sanitize". A
    typo must not silently fail open on a security-relevant setting.
    """
    # ``has_domain_context`` reads the context stack without emitting the
    # "working outside of domain context" warning that a bare ``current_domain``
    # truthiness check would. Imported locally to avoid a domain <-> fields
    # import cycle, matching the other call sites in the codebase.
    from protean.domain.context import has_domain_context  # noqa: PLC0415

    if not has_domain_context():
        return False
    try:
        raw = current_domain.config["field_defaults"]["sanitize"]
    except KeyError:
        return False
    return _coerce_sanitize_flag(raw)


def _coerce_sanitize_flag(raw: Any) -> bool:
    """Read a ``field_defaults.sanitize`` config value as a bool.

    A real bool passes straight through. Config env-var interpolation only ever
    yields strings, so ``[field_defaults] sanitize = "${SANITIZE|false}"`` with
    the var unset resolves to the string ``"false"``; a plain ``bool(...)`` on
    that reads True and would silently sanitize, the opposite of what the
    operator wrote. Parse the recognized string spellings instead
    (case-insensitive), which are the same set the config validator accepts.

    Anything else is malformed. ``Config2._validate_field_defaults`` rejects it
    at load, so it only reaches here from a config mutated in place after load;
    raise rather than read it as "do not sanitize".
    """
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in TRUTHY_FLAG_SPELLINGS:
            return True
        if text in FALSY_FLAG_SPELLINGS:
            return False
    raise ConfigurationError(
        f"`field_defaults.sanitize` must be a boolean, got {raw!r}",
        code=DiagnosticCode.CONFIG_INVALID_FIELD_DEFAULTS,
        location="Config2 ([field_defaults] sanitize)",
    )


def _make_sanitize_validator(
    min_length: int | None, max_length: int | None, always: bool
) -> Callable[[Any], Any]:
    """Build the sanitization validator, re-enforcing the field's length bounds
    on the *sanitized* value.

    ``bleach.clean`` both lengthens (``&`` -> ``&amp;``) and shortens (stripping
    HTML comments / disallowed attributes) a string. The core ``min_length`` /
    ``max_length`` constraints run first, on the *raw* input, but the value that
    gets stored is the sanitized one, so a within-bounds input can be stored
    out of bounds, and re-validating that stored value on a serialization
    round-trip or event-sourced replay then fails. Re-checking the bounds here,
    against the sanitized (stored) form, keeps the field self-consistent: the
    stored value always satisfies its length bounds, so it round-trips. See
    ADR-0026.

    When *always* is False the field left the ``sanitize`` option unset, so the
    validator cleans only when the active domain turns sanitization on via
    ``[field_defaults] sanitize = true``; otherwise it returns the value
    untouched and the length re-enforcement is skipped, so an unsanitized field
    keeps its raw-input bounds behavior. When *always* is True (an explicit
    ``sanitize=True``) it always cleans.
    """

    def _sanitize(v: Any) -> Any:
        if not always and not _domain_default_sanitize():
            return v
        cleaned = _sanitize_string(v)
        if isinstance(cleaned, str):
            length = len(cleaned)
            if max_length is not None and length > max_length:
                raise ValueError(
                    f"String has {length} characters after sanitization, "
                    f"exceeding max_length of {max_length}"
                )
            if min_length is not None and length < min_length:
                raise ValueError(
                    f"String has {length} characters after sanitization, "
                    f"below min_length of {min_length}"
                )
        return cleaned

    return _sanitize
