from protean import Domain, handle
from protean.fields import List, String
from protean.utils.globals import current_domain

domain = Domain(name="Hubspot")
domain.config["event_processing"] = "sync"


# --8<-- [start:model]
@domain.aggregate
class Client:
    hubspot_id: String(required=True)
    name: String(max_length=200)
    contacts: List(content_type=String)

    def update_contacts(self, contacts: list[str]) -> None:
        self.contacts = contacts


@domain.repository(part_of=Client)
class ClientRepository:
    def get_by_hubspot_id(self, hubspot_id: str) -> Client:
        return self.find_by(hubspot_id=hubspot_id)


@domain.event(part_of=Client)
class HubspotClientCreated:
    hubspot_id: String(required=True)
    name: String(required=True)


@domain.event(part_of=Client)
class HubspotAssociationChanged:
    hubspot_id: String(required=True)
    contacts: List(content_type=String)


# --8<-- [end:model]


# --8<-- [start:single_handler]
@domain.event_handler(part_of=Client)
class HubspotClientHandler:
    @handle(HubspotClientCreated)
    def on_created(self, event: HubspotClientCreated):
        repo = current_domain.repository_for(Client)
        client = Client(hubspot_id=event.hubspot_id, name=event.name)
        repo.add(client)

    @handle(HubspotAssociationChanged)
    def on_association_changed(self, event: HubspotAssociationChanged):
        repo = current_domain.repository_for(Client)
        client = repo.get_by_hubspot_id(event.hubspot_id)
        # No "find or create": the Client was created by on_created,
        # which ran first because events are ordered within a handler
        client.update_contacts(event.contacts)
        repo.add(client)


# --8<-- [end:single_handler]
