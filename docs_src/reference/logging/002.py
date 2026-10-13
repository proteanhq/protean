from protean import Domain

domain = Domain(name="Orders")

# --8<-- [start:domain-configure-logging]
domain.configure_logging()  # settings from domain.toml [logging]
domain.configure_logging(level="DEBUG", format="json")  # explicit values win
# --8<-- [end:domain-configure-logging]
