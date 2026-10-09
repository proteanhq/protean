from protean import Domain

domain = Domain(name="Tooling")

# --8<-- [start:close]
try:
    with domain.domain_context():
        ...  # do the work
finally:
    domain.close()
# --8<-- [end:close]
