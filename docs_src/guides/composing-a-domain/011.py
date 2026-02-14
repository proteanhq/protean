import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from protean import Domain

domain = Domain()


@domain.aggregate
class User:
    id: str | None = None
    email: str | None = None
    name: str | None = None


@domain.database_model(part_of=User)
class UserCustomModel:
    id = sa.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = sa.Column(sa.String(50))
    email = sa.Column(sa.String(254))

    class Meta:
        schema_name = "customers"
