import re

from protean import Domain
from protean.fields import String

domain = Domain(__file__, load_toml=False)


class EmailValidator:
    def __init__(self):
        self.error = "Invalid Email Address"

    def __call__(self, email):
        # Define the regular expression pattern for valid email addresses
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9]+\.[a-zA-Z]{2,}$"

        # Match the email with the pattern
        if not bool(re.match(pattern, email)):
            raise ValueError(f"{self.error} - {email}")


@domain.aggregate
class Person:
    name = String(required=True, max_length=50)
    email = String(required=True, max_length=254, validators=[EmailValidator()])
