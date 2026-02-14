from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None


class Register(BaseCommand):
    user_id: str = Field(json_schema_extra={"identifier": True})
    email: str | None = None
    name: str | None = None


def test_domain_stores_command_type_for_easy_retrieval(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.init(traverse=False)

    assert Register.__type__ in test_domain._events_and_commands
