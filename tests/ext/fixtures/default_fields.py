"""Fixture: fields with defaults resolve to base type (not Optional)."""

from protean.fields import String, Integer, Float, Boolean

# Fields with explicit defaults → base type (not Optional)
s = String(default="hello")
reveal_type(s)  # E: Revealed type is "builtins.str"

i = Integer(default=0)
reveal_type(i)  # E: Revealed type is "builtins.int"

f = Float(default=0.0)
reveal_type(f)  # E: Revealed type is "builtins.float"

b = Boolean(default=True)
reveal_type(b)  # E: Revealed type is "builtins.bool"
