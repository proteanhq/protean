"""A rebuild replays stored events through the domain's upcasters."""

import pytest

from protean import Domain, current_domain
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.core.upcaster import BaseUpcaster
from protean.fields import Identifier, String
from protean.utils.eventing import Message


class Account(BaseAggregate):
    name: String()


class Opened(BaseEvent):
    __version__ = 2

    account_id: Identifier(required=True)
    name: String()
    currency: String(required=True)


class UpcastOpenedV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        return {**data, "currency": "USD"}


class AccountView(BaseProjection):
    account_id: Identifier(identifier=True)
    currency: String()


class AccountViewProjector(BaseProjector):
    @on(Opened)
    def on_opened(self, event: Opened) -> None:
        current_domain.repository_for(AccountView).add(
            AccountView(account_id=event.account_id, currency=event.currency)
        )


def _v1_opened_message() -> Message:
    class Opened(BaseEvent):  # the same event before the version bump
        account_id: Identifier(required=True)
        name: String()

    old_domain = Domain(name="Rebuild")
    old_domain.register(Account)
    old_domain.register(Opened, part_of=Account)
    old_domain.init(traverse=False)
    with old_domain.domain_context():
        account = Account(name="Old")
        account.raise_(Opened(account_id=account.id, name="Old"))
        return Message.from_domain_object(account._events[-1])


@pytest.mark.no_test_domain
def test_rebuild_replays_an_older_event_version_through_its_upcaster():
    domain = Domain(name="Rebuild")
    domain.register(Account)
    domain.register(Opened, part_of=Account)
    domain.upcaster(UpcastOpenedV1ToV2, event_type=Opened, from_version=1, to_version=2)
    domain.register(AccountView)
    domain.register(
        AccountViewProjector, projector_for=AccountView, aggregates=[Account]
    )
    domain.init(traverse=False)

    message = _v1_opened_message()
    assert message.metadata.headers.type == "Rebuild.Opened.v1"

    with domain.domain_context():
        domain.event_store.store._write(
            message.metadata.headers.stream,
            message.metadata.headers.type,
            message.data,
            metadata=message.metadata.to_dict(),
        )

        result = domain.rebuild_projection(AccountView)

        assert result.success
        view = current_domain.repository_for(AccountView).get(
            message.data["account_id"]
        )
        assert view.currency == "USD"
