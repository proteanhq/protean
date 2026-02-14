"""Fixture: identifier fields are never Optional."""

from protean.fields import Identifier, Auto

# Identifier with identifier=True → not Optional
id_field = Identifier(identifier=True)
reveal_type(id_field)  # E: Revealed type is "builtins.str"

# Auto field
auto_field = Auto(identifier=True)
reveal_type(auto_field)  # E: Revealed type is "builtins.str"

# Plain Identifier without identifier=True and no default → Optional
plain_id = Identifier()
reveal_type(plain_id)  # E: Revealed type is "builtins.str | None"
