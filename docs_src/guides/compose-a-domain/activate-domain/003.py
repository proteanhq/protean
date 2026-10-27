from protean import Domain, has_domain_context

domain = Domain()
domain.init(traverse=False)

# --8<-- [start:check]
active_before = has_domain_context()  # False

with domain.domain_context():
    active_inside = has_domain_context()  # True

active_after = has_domain_context()  # False
# --8<-- [end:check]
