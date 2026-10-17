from protean import Domain, handle
from protean.fields import List, String
from protean.utils.globals import current_domain

domain = Domain(name="Hubspot")
domain.config["event_processing"] = "sync"


# --8<-- [start:aggregate]
@domain.aggregate
class Client:
    hubspot_id: String(required=True, unique=True)
    name: String(max_length=200)
    contacts: List(content_type=String)

    def update_contacts(self, contacts: list[str]) -> None:
        self.contacts = contacts  # Set-based, naturally idempotent


@domain.repository(part_of=Client)
class ClientRepository:
    def get_by_hubspot_id(self, hubspot_id: str) -> Client:
        return self.find_by(hubspot_id=hubspot_id)

    def exists_for(self, hubspot_id: str) -> bool:
        return self.query.filter(hubspot_id=hubspot_id).count() > 0


# --8<-- [end:aggregate]


@domain.event(part_of=Client)
class HubspotClientCreated:
    hubspot_id: String(required=True)
    name: String(required=True)


@domain.event(part_of=Client)
class HubspotAssociationChanged:
    hubspot_id: String(required=True)
    contacts: List(content_type=String)


# --8<-- [start:handler]
@domain.event_handler(part_of=Client)
class HubspotClientHandler:
    @handle(HubspotClientCreated)
    def on_created(self, event: HubspotClientCreated):
        repo = current_domain.repository_for(Client)
        if repo.exists_for(event.hubspot_id):
            return  # An earlier delivery already created this Client

        # Two runs can both pass the check above. The unique constraint
        # makes the second add raise a ValidationError, so no duplicate
        # is written and that run's transaction rolls back.
        repo.add(Client(hubspot_id=event.hubspot_id, name=event.name))

    @handle(HubspotAssociationChanged)
    def on_association_changed(self, event: HubspotAssociationChanged):
        repo = current_domain.repository_for(Client)
        client = repo.get_by_hubspot_id(event.hubspot_id)
        client.update_contacts(event.contacts)
        repo.add(client)


# --8<-- [end:handler]
