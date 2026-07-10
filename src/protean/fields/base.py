"""Module for defining base Field class"""

import enum
from abc import ABCMeta, abstractmethod
from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import Any, ClassVar

from protean import exceptions
from protean.fields.mixins import FieldDescriptorMixin
from protean.utils import _normalize_deprecated

MISSING_ERROR_MESSAGE = (
    "ValidationError raised by `{class_name}`, but error key `{key}` does "
    "not exist in the `error_messages` dictionary."
)

# Values treated as "empty": they trigger the ``required`` check and short-circuit
# per-field validators (validators must not run on an omitted optional field).
# Shared with the Pydantic-based field system in ``spec.py`` so both stay aligned.
EMPTY_VALUES: tuple[Any, ...] = (None, "", [], (), {})


def normalize_field_renamed_from(
    value: str | list[str] | tuple[str, ...] | None,
) -> list[str] | None:
    """Normalize the ``renamed_from`` field parameter to a list of aliases.

    Accepts:
    - ``None`` / empty → ``None``
    - ``"old_name"`` (single alias) → ``["old_name"]``
    - ``["a", "b"]`` / ``("a", "b")`` (aliases) → ``["a", "b"]``

    Each alias must be a non-empty string. Raises :class:`ValueError` on
    invalid input.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = [value]
    elif isinstance(value, (list, tuple)):
        value = list(value)
    else:
        raise ValueError(
            f"Invalid `renamed_from` value: {value!r}. "
            "Expected a field-name string or a list of field-name strings."
        )

    aliases: list[str] = []
    for alias in value:
        if not isinstance(alias, str) or not alias:
            raise ValueError(
                f"Invalid `renamed_from` alias: {alias!r}. "
                "Each alias must be a non-empty field-name string."
            )
        aliases.append(alias)
    return aliases or None


class FieldBase:
    """Base class for all Protean fields.

    For now, this is a marker class to support later attribute discovery.
    """

    _auto_generated: bool = False


class Field(FieldBase, FieldDescriptorMixin, metaclass=ABCMeta):
    """
    Base class for all fields in the Protean framework.

    Fields are used to define the structure and behavior of attributes in an entity or aggregate.
    They handle the validation, conversion, and storage of attribute values.

    Fields are descriptors, which means they are assigned to a class attribute and are used to
    manage the attribute's value. When a field is assigned to a class, it is given a name on the
    class. This name is used to access the field value from the instance.

    The values are validated and converted to the appropriate type when they are set on the
    instance. This is done by the `_load` method, which is called by the `__set__` method.
    The values are set up on the `__dict__` of the instance, so they are NEVER stored on the field
    itself.

    Parameters:
    - `referenced_as`: The name of the attribute in the underlying data store.
    - `description`: A human-readable description of the field.
    - `identifier`: A boolean indicating if this field is the identifier for the entity.
    - `default`: The default value for the field.
    - `required`: A boolean indicating if this field is required.
    - `unique`: A boolean indicating if this field must be unique.
    - `choices`: An Enum class that defines the valid choices for this field.
    - `validators`: A list of callables that validate the field value.
    - `error_messages`: A dictionary of error messages for validation errors.
    """

    default_error_messages: ClassVar[dict[str, str]] = {
        "invalid": "Value is not a valid type for this field.",
        "unique": "{entity_name} with {field_name} '{value}' is already present.",
        "required": "is required",
        "invalid_choice": "Value `{value!r}` is not a valid choice. "
        "Must be among {choices!r}",
    }

    # Default validators for a Field
    default_validators: ClassVar[list[Callable[..., Any]]] = []

    # These values will trigger the self.required check.
    empty_values: tuple[Any, ...] = EMPTY_VALUES

    def __init__(
        self,
        referenced_as: str | None = None,
        description: str | None = None,
        identifier: bool = False,
        default: Any = None,
        required: bool = False,
        unique: bool = False,
        choices: type[enum.Enum] | list[Any] | tuple[Any, ...] | None = None,
        validators: Iterable[Callable[..., Any]] = (),
        error_messages: dict[str, str] | None = None,
        deprecated: str | dict[str, Any] | None = None,
        renamed_from: str | list[str] | tuple[str, ...] | None = None,
    ):
        # Pass to FieldDescriptorMixin for initialization
        super().__init__(referenced_as=referenced_as, description=description)

        self.identifier = identifier
        self.default = default
        self.deprecated = _normalize_deprecated(deprecated)
        # Old field name(s) this field was renamed from. Resolved at
        # deserialization time so a stored payload written under the old key
        # loads into this field without an upcaster.
        self.renamed_from = normalize_field_renamed_from(renamed_from)

        # Indicates if field values need to be unique within the repository
        # always True for identifier field
        self.unique = True if self.identifier else unique

        # Indicates if this field is required, always True for identifier field
        self.required = True if self.identifier else required

        # Set the choices for this field
        self.choices = choices

        self._validators = validators

        # Collect default error message from self and parent classes
        messages: dict[str, str] = {}
        for cls in reversed(self.__class__.__mro__):
            messages.update(getattr(cls, "default_error_messages", {}))
        messages.update(error_messages or {})
        self.error_messages = messages

    def _generic_param_values_for_repr(self) -> list[str]:
        """Return the generic parameter values for the Field's repr"""
        values = []
        if self.description:
            values.append(f"description='{self.description}'")
        if self.identifier:
            values.append("identifier=True")
        if not self.identifier and self.required:
            values.append("required=True")
        if self.referenced_as:
            values.append(f"referenced_as='{self.referenced_as}'")
        if self.default is not None:
            # If default is a callable, use its name
            if callable(self.default):
                values.append(f"default={self.default.__name__}")
            else:
                if isinstance(self.default, str):
                    values.append(f"default='{self.default}'")
                else:
                    values.append(f"default={self.default}")
        return values

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            + ", ".join(self._generic_param_values_for_repr())
            + ")"
        )

    def __get__(self, instance: Any, owner: Any) -> Any:
        if hasattr(instance, "__dict__"):
            return instance.__dict__.get(self.field_name)

    def __set__(self, instance: Any, value: Any) -> None:
        value = self._load(value)

        # The hasattr check is necessary to avoid running invariant checks on unrelated elements
        if (
            instance._initialized
            and hasattr(instance, "_root")
            and instance._root is not None
        ):
            instance._root._precheck()  # Trigger validations from the top

        instance.__dict__[self.field_name] = value

        # The hasattr check is necessary to avoid running invariant checks on unrelated elements
        if (
            instance._initialized
            and hasattr(instance, "_root")
            and instance._root is not None
        ):
            instance._root._postcheck()  # Trigger validations from the top

        # Mark Entity as Dirty
        if hasattr(instance, "state_"):
            instance.state_.mark_changed()

    def __delete__(self, instance: Any) -> None:
        instance.__dict__.pop(self.field_name, None)

    def fail(self, key: str, **kwargs: Any) -> None:
        """A helper method that simply raises a `ValidationError`."""
        try:
            msg = self.error_messages[key]
        except KeyError as e:
            class_name = self.__class__.__name__
            msg = MISSING_ERROR_MESSAGE.format(class_name=class_name, key=key)
            raise exceptions.ValidationError({key: [msg]}) from e

        # Format message with supplied arguments
        msg = msg.format(**kwargs)

        # If a field is being used by itself (not owned by an entity/aggregate),
        #   it's field_name will be blank.
        field_name = self.field_name or "unlinked"
        raise exceptions.ValidationError({field_name: [msg]})

    @property
    def validators(self) -> list[Callable[..., Any]]:
        """
        Some validators can't be created at field initialization time.
        This method provides a way to handle such default validators.
        """
        return [*self.default_validators, *self._validators]

    @abstractmethod
    def _cast_to_type(self, value: Any) -> Any:
        """
        Abstract method to validate and convert the value passed to native type.
        All subclasses must implement this method.
        Raise a :exc:`ValidationError` if validation does not succeed.
        """

    @abstractmethod
    def as_dict(self, value: Any) -> Any:
        """Return JSON-compatible value of field"""

    def _run_validators(self, value: Any) -> None:
        """Perform validation on ``value``. Raise a :exc:`ValidationError` if
        validation does not succeed.
        """
        if value in self.empty_values:
            return

        errors: defaultdict[str, list[Any]] = defaultdict(list)
        for validator in self.validators:
            try:
                validator(value)
            except exceptions.ValidationError as err:
                field_name = self.field_name or "unlinked"
                errors[field_name].append(err.messages)

        if errors:
            raise exceptions.ValidationError(errors)

    def _clone(self) -> "Field":
        """
        Clone the field with all its attributes.

        :return: Cloned Field object
        """
        return self.__class__(
            referenced_as=self.referenced_as,
            description=self.description,
            identifier=self.identifier,
            default=self.default,
            required=self.required,
            unique=self.unique,
            choices=self.choices,
            validators=self._validators,
            error_messages=self.error_messages,
            deprecated=self.deprecated,
            renamed_from=self.renamed_from,
        )

    def _load(self, value: Any) -> Any:
        """
        Load the value for the field, run validators and return the value.
        Subclasses can override this to provide custom load logic.

        :param value: value of the field

        """

        # Check if value is one among recognized empty values, or is False (for complex objects)
        if value in self.empty_values:
            # If a default has been set for the field return it
            if self.default is not None:
                default = self.default
                value = default() if callable(default) else default
                return value

            # If no default is set and this field is required
            elif self.required:
                self.fail("required")

            # In all other cases just return the passed value, as we do not want to
            # run validations against an empty value
            # Because of this behavior, we preserve the data sanctity for int and float objects,
            # and return 0 or 0.0, as need be.
            elif value is None:
                return value

        # If choices exist then validate that value is be one of the choices
        if self.choices:
            choices: list[Any] | tuple[Any, ...]
            # A list/tuple of choices is used as-is; otherwise it is an Enum class
            if isinstance(self.choices, (list, tuple)):
                choices = self.choices
            else:
                enum_cls = self.choices
                choices = [item.value for item in enum_cls]

                # Check if value is an Enum instance
                if isinstance(value, enum_cls):
                    value = value.value

            value_list = [value] if not isinstance(value, (list, tuple)) else value

            for v in value_list:
                if v not in choices:
                    self.fail("invalid_choice", value=v, choices=choices)

        # Cast and Validate the value for this Field
        value = self._cast_to_type(value)

        # Call the rest of the validators defined for this Field
        self._run_validators(value)

        return value
