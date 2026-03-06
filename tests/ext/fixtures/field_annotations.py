"""Fixture: field descriptors used as type annotations resolve correctly.

Tests that ``name: String``, ``price: Float``, etc. are accepted by mypy
as valid type annotations (not rejected with [valid-type] errors).
"""

from protean.fields import (
    Boolean,
    Date,
    DateTime,
    Float,
    Identifier,
    Integer,
    String,
    Text,
)

# Bare annotation — field type used as a type (common in events)
s: String
reveal_type(s)  # E: Revealed type is "builtins.str"

t: Text
reveal_type(t)  # E: Revealed type is "builtins.str"

i: Integer
reveal_type(i)  # E: Revealed type is "builtins.int"

f: Float
reveal_type(f)  # E: Revealed type is "builtins.float"

b: Boolean
reveal_type(b)  # E: Revealed type is "builtins.bool"

d: Date
reveal_type(d)  # E: Revealed type is "datetime.date"

dt: DateTime
reveal_type(dt)  # E: Revealed type is "datetime.datetime"

ident: Identifier
reveal_type(ident)  # E: Revealed type is "builtins.str"
