from protean import Domain

domain = Domain(name="Ordering")

# --8<-- [start:config]
# Domain-wide configuration
domain.config["event_processing"] = "async"  # or "sync"
domain.config["command_processing"] = "sync"  # or "async"
# --8<-- [end:config]
