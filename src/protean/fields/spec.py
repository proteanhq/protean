"""FieldSpec — domain-native field declaration carrier.

A FieldSpec is a plain data object that carries type information and constraints.
It is consumed during class creation and translated into Pydantic-compatible
``Annotated[type, Field(...)]`` annotations.  After the metaclass runs, only
Pydantic's native machinery remains — FieldSpec itself is not stored on the class.
"""

import warnings
from enum import Enum
from typing import Any, Callable, Iterable


# ---------------------------------------------------------------------------
# Sentinel for "no default provided"
# ---------------------------------------------------------------------------
class _UNSET_TYPE:
    """Sentinel indicating no default was provided."""

    _instance = None

    def __new__(cls):
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
    class creation.  It is **not** a descriptor — it has no ``__get__`` or
    ``__set__`` — and is discarded after the class is built.
    """

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
        choices: tuple | list | type | None = None,  # supports Enum classes too
        description: str = "",
        referenced_as: str | None = None,
        # Type-specific constraints
        max_length: int | None = None,
        min_length: int | None = None,
        max_value: float | int | None = None,
        min_value: float | int | None = None,
        # Container-specific
        content_type: Any = None,  # For List fields
        # Sanitization
        sanitize: bool = False,  # For String/Text — runs bleach.clean()
        # Validators
        validators: Iterable[Callable] = (),  # Per-field validator callables
        # Error messages
        error_messages: dict[str, str] | None = None,
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
        self.content_type = content_type
        self.sanitize = sanitize
        self.validators = list(validators)
        self.error_messages = error_messages

        # Warn if required=True with an explicit default
        if self.required and self.default is not _UNSET:
            warnings.warn(
                "Field declared with required=True and an explicit default. "
                "The default will be honored; the field is effectively not required.",
                stacklevel=3,
            )

    # ------------------------------------------------------------------
    # Resolution methods
    # ------------------------------------------------------------------
    def resolve_type(self) -> type:
        """Return the Python type annotation for Pydantic.

        Handles choices → Literal, and optional wrapping.
        """
        from typing import Literal, Optional

        resolved = self.python_type

        # If choices is set, replace with Literal
        if self.choices is not None:
            if isinstance(self.choices, type) and issubclass(self.choices, Enum):
                choices_values = tuple(item.value for item in self.choices)
            else:
                choices_values = tuple(self.choices)
            resolved = Literal[choices_values]  # type: ignore[valid-type]

        # Wrap in Optional when not required, no explicit default, and not identifier.
        # Auto-increment identifiers are also Optional since the DAO assigns
        # the actual integer value at persistence time.
        is_increment_id = self.identifier and getattr(self, "_increment", False)
        if (
            not self.required
            and self.default is _UNSET
            and (not self.identifier or is_increment_id)
        ):
            resolved = Optional[resolved]

        return resolved

    def resolve_field_kwargs(self) -> dict[str, Any]:
        """Return the kwargs dict for ``pydantic.Field(...)``."""
        from uuid import uuid4

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

        # Handle identifier
        if self.identifier:
            json_extra["identifier"] = True
            if self.default is _UNSET:
                if getattr(self, "_increment", False):
                    # Auto-increment identifiers: the DAO handles the
                    # actual value generation; default to None here.
                    kwargs["default"] = None
                elif self.field_kind in ("identifier", "auto"):
                    # Use generate_identity with identity_* options from Auto()
                    _id_strategy = getattr(self, "_identity_strategy", None)
                    _id_function = getattr(self, "_identity_function", None)
                    _id_type = getattr(self, "_identity_type", None)

                    from protean.utils import generate_identity

                    kwargs["default_factory"] = (
                        lambda s=_id_strategy, f=_id_function, t=_id_type: (
                            generate_identity(
                                identity_strategy=s,
                                identity_function=f,
                                identity_type=t,
                            )
                        )
                    )

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
        if self.sanitize:
            json_extra["sanitize"] = True
        if getattr(self, "_increment", False):
            json_extra["increment"] = True
        if self.validators:
            json_extra["_validators"] = list(self.validators)
        if self.error_messages:
            json_extra["_error_messages"] = self.error_messages

        if json_extra:
            kwargs["json_schema_extra"] = json_extra

        return kwargs

    def resolve_annotated(self) -> type:
        """Combine resolved type and field kwargs into ``Annotated[type, Field(...)]``.

        When ``sanitize=True`` or per-field ``validators`` are present, the
        corresponding ``AfterValidator`` wrappers are appended to the
        ``Annotated`` metadata.
        """
        from typing import Annotated

        from pydantic import AfterValidator, BeforeValidator
        from pydantic import Field as PydanticField

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

        # Sanitization via AfterValidator
        if (
            self.sanitize
            and isinstance(self.python_type, type)
            and issubclass(self.python_type, str)
        ):
            extra_validators.append(AfterValidator(_sanitize_string))

        # Per-field validators via AfterValidator
        if self.validators:
            captured_validators = list(self.validators)

            def _run_protean_validators(
                v: Any,
                validators: list[Callable] = captured_validators,
            ) -> Any:
                from protean.exceptions import ValidationError as ProteanValidationError

                for validator_fn in validators:
                    try:
                        validator_fn(v)
                    except ProteanValidationError as e:
                        # Re-raise as ValueError so Pydantic catches it and
                        # maps it to the correct field name.
                        msg = str(e.messages) if hasattr(e, "messages") else str(e)
                        # If the validator set an error string on itself, use that
                        if hasattr(validator_fn, "error"):
                            msg = validator_fn.error
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

    def __repr__(self) -> str:
        import datetime as _dt

        # Map (python_type, field_kind) to user-friendly factory name
        _FACTORY_NAMES: dict[tuple[type, str], str] = {
            (str, "standard"): "String",
            (str, "text"): "Text",
            (str, "identifier"): "Identifier",
            (str, "auto"): "Auto",
            (int, "auto"): "Auto",
            (int, "standard"): "Integer",
            (float, "standard"): "Float",
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
        # Show sanitize only when it deviates from the factory default
        if factory_name in ("String", "Text") and not self.sanitize:
            parts.append("sanitize=False")
        # Show increment for Auto fields
        if factory_name == "Auto" and getattr(self, "_increment", False):
            parts.append("increment=True")
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
    own_annots = vars(cls).get("__annotations__", {})
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
        try:
            delattr(cls, name)
        except AttributeError:
            pass

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
        existing = getattr(cls, "__protean_field_meta__", {})
        cls.__protean_field_meta__ = {**existing, **field_meta}


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
        import bleach

        return bleach.clean(v)
    except ImportError:
        return v
