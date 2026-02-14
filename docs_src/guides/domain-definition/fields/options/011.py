from protean import Domain
from pydantic import Field

domain = Domain()


@domain.aggregate
class Building:
    doors: int = Field(
        json_schema_extra={"error_messages": {"required": "Every building needs some!"}}
    )
