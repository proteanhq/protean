import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from protean import Domain
from protean.fields import Identifier, String

domain = Domain(__file__)


@domain.aggregate
class User:
    id = Identifier()
    email = String()
    name = String()


@domain.model(part_of=User)
class UserCustomModel:
    id = sa.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = sa.Column(sa.String(50))
    email = sa.Column(sa.String(254))

    class Meta:
        schema_name = "customers"
