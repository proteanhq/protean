from protean import Domain

domain = Domain(name="Ordering")

# --8<-- [start:config]
# Configure events to be processed synchronously
domain.config["event_processing"] = "sync"  # or "async"
# --8<-- [end:config]
