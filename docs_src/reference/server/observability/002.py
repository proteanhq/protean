from protean import Domain

domain = Domain(name="Monitoring")

# --8<-- [start:cors]
from protean.server.observatory import Observatory

observatory = Observatory(
    domains=[domain],
    enable_cors=True,
    cors_origins=["https://monitoring.example.com"],
)
# --8<-- [end:cors]
