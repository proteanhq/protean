"""
Composing Multiple Validators

This example demonstrates:
- Chaining multiple validators on a single field
- Combining built-in RegexValidator with custom validators
- Error collection from multiple validators
- Building layered validation (format + business rule + deny-list)
- Custom error message patterns

Scenario:
    A UserAccount aggregate has a username field that must pass several
    validation rules: format, reserved words, and profanity checks.
    A Coupon aggregate has a code that must match a pattern and not be expired.

Usage:
    account = UserAccount(
        username="john_doe",
        display_name="John Doe",
    )
"""

from protean import Domain
from protean.exceptions import ValidationError
from protean.fields import String
from protean.fields.validators import RegexValidator

# Domain setup
domain = Domain(__name__)


class ReservedWordValidator:
    """Rejects values that match reserved/system words.

    Configurable with a list of reserved words.
    Comparison is case-insensitive.
    """

    def __init__(self, reserved_words):
        self.reserved_words = [w.lower() for w in reserved_words]

    def __call__(self, value):
        if value.lower() in self.reserved_words:
            raise ValidationError(f"'{value}' is reserved and cannot be used")


class NoProfanityValidator:
    """Rejects values containing blocked words.

    Checks for substring matches (case-insensitive).
    """

    def __init__(self, blocked_words=None):
        self.blocked_words = [w.lower() for w in (blocked_words or [])]

    def __call__(self, value):
        lower_val = value.lower()
        for word in self.blocked_words:
            if word in lower_val:
                raise ValidationError("Value contains prohibited content")


class NoConsecutiveSpecialCharsValidator:
    """Rejects values with consecutive special characters.

    Prevents strings like '__', '--', '..', etc.
    """

    def __init__(self, special_chars="_-."):
        self.special_chars = special_chars

    def __call__(self, value):
        for i in range(len(value) - 1):
            if value[i] in self.special_chars and value[i + 1] in self.special_chars:
                raise ValidationError("Cannot contain consecutive special characters")


class PrefixValidator:
    """Validates that a string starts with one of the allowed prefixes."""

    def __init__(self, prefixes, case_sensitive=True):
        self.prefixes = prefixes
        self.case_sensitive = case_sensitive
        self.error = f"Must start with one of: {', '.join(prefixes)}"

    def __call__(self, value):
        check_value = value if self.case_sensitive else value.lower()
        check_prefixes = (
            self.prefixes if self.case_sensitive else [p.lower() for p in self.prefixes]
        )
        if not any(check_value.startswith(p) for p in check_prefixes):
            raise ValidationError(self.error)


# --- Composed validator sets ---

# Username: format + reserved words + no profanity + no consecutive specials
username_format = RegexValidator(
    regex=r"^[a-zA-Z][a-zA-Z0-9_.-]{2,29}$",
    message="Username must start with a letter, 3-30 chars, only letters/digits/underscore/dot/dash",
)
username_reserved = ReservedWordValidator(
    reserved_words=["admin", "root", "system", "moderator", "support"]
)
username_profanity = NoProfanityValidator(blocked_words=["spam", "hack"])
username_consecutive = NoConsecutiveSpecialCharsValidator()

# Coupon code: prefix + format
coupon_prefix = PrefixValidator(prefixes=["SAVE", "DISC", "FREE"], case_sensitive=True)
coupon_format = RegexValidator(
    regex=r"^[A-Z]{4}-[A-Z0-9]{4,8}$",
    message="Coupon code must be in format XXXX-YYYY (4 letter prefix, dash, 4-8 alphanumeric)",
)


@domain.aggregate
class UserAccount:
    """User account with heavily validated username."""

    username: String(
        required=True,
        max_length=30,
        identifier=True,
        validators=[
            username_format,
            username_reserved,
            username_profanity,
            username_consecutive,
        ],
    )
    display_name: String(required=True, max_length=100)


@domain.aggregate
class Coupon:
    """Coupon with prefix and format validation."""

    code: String(
        required=True,
        max_length=13,
        identifier=True,
        validators=[coupon_prefix, coupon_format],
    )
    description: String(max_length=200)


if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)
    with domain.domain_context():
        # Valid username
        account = UserAccount(username="john_doe", display_name="John Doe")
        print(f"Account created: {account.username}")

        # Reserved username
        try:
            UserAccount(username="admin", display_name="Admin")
        except ValidationError as e:
            print(f"Reserved rejected: {e}")

        # Profanity in username
        try:
            UserAccount(username="hackmaster", display_name="Hacker")
        except ValidationError as e:
            print(f"Profanity rejected: {e}")

        # Consecutive special chars
        try:
            UserAccount(username="john__doe", display_name="John")
        except ValidationError as e:
            print(f"Consecutive specials rejected: {e}")

        # Valid coupon
        coupon = Coupon(code="SAVE-ABC123", description="10% off")
        print(f"Coupon: {coupon.code}")

        # Invalid coupon prefix
        try:
            Coupon(code="XXXX-ABC123")
        except ValidationError as e:
            print(f"Bad prefix: {e}")
