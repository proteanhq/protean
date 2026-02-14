from __future__ import annotations

from abc import abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

from protean.core.value_object import _PydanticFieldShim, _convert_pydantic_errors
from protean.exceptions import ValidationError
from protean.utils import (
    DomainObjects,
    convert_str_values_to_list,
    derive_element_class,
)
from protean.utils.container import OptionsMixin
from protean.utils.reflection import _FIELDS


class BaseEmailProvider:
    """
    Base class for email backend implementations.

    Concrete implementations must overwrite `send_email()`.
    ```
    """

    def __init__(self, name, domain, conn_info, fail_silently=False, **kwargs):
        self.name = name
        self.domain = domain
        self.conn_info = conn_info
        self.fail_silently = fail_silently

    @abstractmethod
    def send_email(self, email_message):
        """Send EmailMessage object via registered email provider."""


# ---------------------------------------------------------------------------
# Pydantic-based BaseEmail
# ---------------------------------------------------------------------------
class BaseEmail(BaseModel, OptionsMixin):
    """Base Email class using Pydantic v2 BaseModel.

    All domain email message classes should inherit from this.
    This is also a marker class referenced when emails are registered
    with the domain.

    Fields are declared using standard Python type annotations.
    """

    element_type: ClassVar[str] = DomainObjects.EMAIL

    model_config = ConfigDict(extra="forbid", ignored_types=(str,))

    @classmethod
    def _default_options(cls) -> list[tuple[str, Any]]:
        return [("provider", "default")]

    # Core email fields
    subject: str | None = None
    from_email: str | None = None
    to: list[str] | str | None = None
    bcc: list[str] | str | None = None
    cc: list[str] | str | None = None
    reply_to: list[str] | str | None = None

    # Supplied content
    text: str | None = None
    html: str | None = None

    # JSON data with template
    data: dict | None = None
    template: str | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Set empty __container_fields__ as placeholder
        setattr(cls, _FIELDS, {})

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Called by Pydantic AFTER model_fields are fully populated."""
        super().__pydantic_init_subclass__(**kwargs)

        # Build __container_fields__ bridge from Pydantic model_fields
        fields_dict: dict[str, _PydanticFieldShim] = {}
        for fname, finfo in cls.model_fields.items():
            fields_dict[fname] = _PydanticFieldShim(fname, finfo, finfo.annotation)
        setattr(cls, _FIELDS, fields_dict)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Support template dict pattern: Email({"key": "val"}, key2="val2")
        if args:
            for template in args:
                if not isinstance(template, dict):
                    raise AssertionError(
                        f"Positional argument {template} passed must be a dict. "
                        f"This argument serves as a template for loading common "
                        f"values.",
                    )
                kwargs.update(template)

        try:
            super().__init__(**kwargs)
        except PydanticValidationError as e:
            raise ValidationError(_convert_pydantic_errors(e))

    def model_post_init(self, __context: Any) -> None:
        self.defaults()

    def defaults(self) -> None:
        """Initialize email fields, converting string values to lists."""
        self.to = convert_str_values_to_list(self.to)
        self.cc = convert_str_values_to_list(self.cc)
        self.bcc = convert_str_values_to_list(self.bcc)
        self.reply_to = (
            convert_str_values_to_list(self.reply_to)
            if self.reply_to
            else self.from_email
        )

    @property
    def recipients(self) -> list[str]:
        """Return list of all recipients (to + cc + bcc)."""
        to = self.to or []
        cc = self.cc or []
        bcc = self.bcc or []
        return [email for email in (to + cc + bcc) if email]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Return email data as a dictionary."""
        result: dict[str, Any] = {}
        for fname, shim in getattr(self, _FIELDS, {}).items():
            result[fname] = shim.as_dict(getattr(self, fname, None))
        return result

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return False
        return self.to_dict() == other.to_dict()

    def __hash__(self) -> int:
        return id(self)

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
def email_factory(element_cls: type, domain: Any, **opts: Any) -> type:
    # Always route to Pydantic base
    base_cls = BaseEmail

    return derive_element_class(element_cls, base_cls, **opts)
