"""The Order aggregate. Hand-owned; a re-run of add must not touch this."""

from myproj.domain import myproj

from protean import invariant
from protean.exceptions import ValidationError

from .aggregate_base import OrderBase

SENTINEL = "developer-owned-marker-4c1f"


@myproj.aggregate
class Order(OrderBase):
    """The Order aggregate root."""

    @invariant.post
    def name_must_not_be_blank(self):
        if not self.name.strip():
            raise ValidationError({"name": ["name must not be blank"]})
