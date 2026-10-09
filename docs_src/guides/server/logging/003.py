from protean import Domain

domain = Domain(name="Orders")

# --8<-- [start:configure]
domain.configure_logging(level="DEBUG", format="json")
# --8<-- [end:configure]
