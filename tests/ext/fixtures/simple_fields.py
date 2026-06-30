"""Fixture: simple field factories resolve to correct Python types."""

from protean.fields import (
    String,
    Text,
    Integer,
    Float,
    Decimal,
    Boolean,
    Date,
    DateTime,
)

# Required fields → base type (not Optional)
s = String(max_length=100, required=True)
reveal_type(s)  # E: Revealed type is "builtins.str"

t = Text(required=True)
reveal_type(t)  # E: Revealed type is "builtins.str"

i = Integer(required=True)
reveal_type(i)  # E: Revealed type is "builtins.int"

f = Float(required=True)
reveal_type(f)  # E: Revealed type is "builtins.float"

dec = Decimal(required=True)
reveal_type(dec)  # E: Revealed type is "decimal.Decimal"

b = Boolean(required=True)
reveal_type(b)  # E: Revealed type is "builtins.bool"

d = Date(required=True)
reveal_type(d)  # E: Revealed type is "datetime.date"

dt = DateTime(required=True)
reveal_type(dt)  # E: Revealed type is "datetime.datetime"
