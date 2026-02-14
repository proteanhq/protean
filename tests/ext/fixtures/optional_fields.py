"""Fixture: non-required fields without defaults resolve to Optional types."""

from protean.fields import String, Integer, Float, Boolean, Date, DateTime

# Non-required fields without defaults → Optional (T | None)
s = String(max_length=100)
reveal_type(s)  # E: Revealed type is "builtins.str | None"

i = Integer()
reveal_type(i)  # E: Revealed type is "builtins.int | None"

f = Float()
reveal_type(f)  # E: Revealed type is "builtins.float | None"

b = Boolean()
reveal_type(b)  # E: Revealed type is "builtins.bool | None"

d = Date()
reveal_type(d)  # E: Revealed type is "datetime.date | None"

dt = DateTime()
reveal_type(dt)  # E: Revealed type is "datetime.datetime | None"
