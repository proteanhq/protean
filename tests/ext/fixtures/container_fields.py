"""Fixture: container fields (List, Dict) resolve to list/dict (never Optional)."""

from protean.fields import List, Dict

# Container fields have implicit defaults → never Optional
lst = List()
reveal_type(lst)  # E: Revealed type is "builtins.list"

# Even without explicit default or required
lst2 = List(content_type=int)
reveal_type(lst2)  # E: Revealed type is "builtins.list"

dct = Dict()
reveal_type(dct)  # E: Revealed type is "builtins.dict"

# Required containers
lst_req = List(required=True)
reveal_type(lst_req)  # E: Revealed type is "builtins.list"

dct_req = Dict(required=True)
reveal_type(dct_req)  # E: Revealed type is "builtins.dict"
