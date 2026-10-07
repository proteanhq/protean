# --8<-- [start:config]
import os

from protean import Domain

domain = Domain(
    config={
        "identity_strategy": "uuid",
        "databases": {
            "default": {
                "provider": "postgresql",
                "database_uri": os.environ.get(
                    "DATABASE_URL", "postgresql://user:pass@localhost/db"
                ),
            }
        },
    }
)
# --8<-- [end:config]
