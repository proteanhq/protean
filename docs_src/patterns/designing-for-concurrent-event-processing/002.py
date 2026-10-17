from protean import Domain, handle
from protean.fields import Boolean, List, String
from protean.utils.globals import current_domain

domain = Domain(name="Hubspot")
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


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


# --8<-- [start:commands]
@domain.command(part_of=Client)
class CreateClient:
    hubspot_id: String(required=True)
    name: String(required=True)


@domain.command(part_of=Client)
class UpdateClientContacts:
    hubspot_id: String(required=True)
    contacts: List(content_type=String)


@domain.command_handler(part_of=Client)
class ClientCommandHandler:
    @handle(CreateClient)
    def create(self, command: CreateClient):
        current_domain.repository_for(Client).add(
            Client(hubspot_id=command.hubspot_id, name=command.name)
        )

    @handle(UpdateClientContacts)
    def update_contacts(self, command: UpdateClientContacts):
        repo = current_domain.repository_for(Client)
        client = repo.get_by_hubspot_id(command.hubspot_id)
        client.update_contacts(command.contacts)
        repo.add(client)


# --8<-- [end:commands]


# --8<-- [start:process_manager]
@domain.process_manager(stream_categories=["hubspot::client"])
class HubspotClientOnboarding:
    hubspot_id: String(identifier=True)
    client_created: Boolean(default=False)
    pending_contacts: List(content_type=String)

    @handle(HubspotClientCreated, start=True, correlate="hubspot_id")
    def on_created(self, event: HubspotClientCreated):
        self.client_created = True
        self.hubspot_id = event.hubspot_id
        current_domain.process(
            CreateClient(hubspot_id=event.hubspot_id, name=event.name)
        )

        # Process any contacts that arrived before the client was created
        if self.pending_contacts:
            current_domain.process(
                UpdateClientContacts(
                    hubspot_id=self.hubspot_id,
                    contacts=self.pending_contacts,
                )
            )
            self.pending_contacts = []

    # start=True as well: the association event can be the first one to
    # arrive, and a process manager skips a non-start event it has no
    # instance for.
    @handle(HubspotAssociationChanged, start=True, correlate="hubspot_id")
    def on_association_changed(self, event: HubspotAssociationChanged):
        if not self.client_created:
            # Buffer: the client has not been created yet
            self.hubspot_id = event.hubspot_id
            self.pending_contacts = event.contacts
            return

        current_domain.process(
            UpdateClientContacts(
                hubspot_id=event.hubspot_id,
                contacts=event.contacts,
            )
        )


# --8<-- [end:process_manager]
