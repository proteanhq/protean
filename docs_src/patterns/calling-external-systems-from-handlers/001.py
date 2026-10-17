import httpx

from protean import Domain, handle
from protean.fields import Auto, Identifier, Integer, List, String
from protean.utils.globals import current_domain

domain = Domain(name="ProfileSync")
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"

# --8<-- [start:aggregates]
FLAGS_FOR_TIER = {
    "free": [],
    "pro": ["exports"],
    "team": ["exports", "sso"],
}


@domain.event(part_of="Subscriber")
class SubscriberSyncRequested:
    subscriber_id: Identifier(required=True)


@domain.event(part_of="ProfileSnapshot")
class ProfileSnapshotStored:
    snapshot_id: Identifier(required=True)
    subscriber_id: Identifier(required=True)


@domain.aggregate
class ProfileSnapshot:
    snapshot_id: Auto(identifier=True)
    subscriber_id: Identifier(required=True)
    email: String(required=True)
    name: String(required=True)
    tier: String(required=True)
    seats: Integer(required=True)

    @classmethod
    def from_payload(cls, subscriber_id, payload):
        return cls(
            subscriber_id=subscriber_id,
            email=payload["email"],
            name=payload["name"],
            tier=payload["plan"]["tier"],
            seats=payload["plan"]["seats"],
        )

    def store(self):
        self.raise_(
            ProfileSnapshotStored(
                snapshot_id=self.snapshot_id, subscriber_id=self.subscriber_id
            )
        )


@domain.aggregate
class Subscriber:
    subscriber_id: Identifier(identifier=True)
    email: String()
    name: String()
    tier: String(default="free")
    seats: Integer(default=1)
    flags: List(content_type=String)
    applied_snapshot_ids: List(content_type=String)

    def request_sync(self):
        self.raise_(SubscriberSyncRequested(subscriber_id=self.subscriber_id))

    def update_contact(self, email, name):
        self.email = email
        self.name = name

    def change_plan(self, tier, seats):
        self.tier = tier
        self.seats = seats

    def set_flags_for_tier(self):
        self.flags = list(FLAGS_FOR_TIER[self.tier])

    def record_snapshot(self, snapshot_id):
        self.applied_snapshot_ids = [*self.applied_snapshot_ids, snapshot_id]


# --8<-- [end:aggregates]


# --8<-- [start:fetch]
BILLING_URL = "https://billing.example.com"


@domain.event_handler(part_of=Subscriber)
class ProfileFetch:
    @handle(SubscriberSyncRequested)
    def fetch_snapshot(self, event):
        # The fetch comes before any repository access, so no transaction is open.
        payload = httpx.get(f"{BILLING_URL}/subscribers/{event.subscriber_id}").json()

        repo = current_domain.repository_for(ProfileSnapshot)
        snapshot = ProfileSnapshot.from_payload(event.subscriber_id, payload)
        snapshot.store()  # raises ProfileSnapshotStored
        repo.add(snapshot)


# --8<-- [end:fetch]


# --8<-- [start:sync]
@domain.command(part_of=Subscriber)
class ApplyProfileSnapshot:
    subscriber_id: Identifier(identifier=True)
    snapshot_id: Identifier(required=True)


@domain.event_handler(part_of=ProfileSnapshot)
class ProfileSnapshotHandler:
    @handle(ProfileSnapshotStored)
    def apply_to_subscriber(self, event: ProfileSnapshotStored):
        current_domain.process(
            ApplyProfileSnapshot(
                subscriber_id=event.subscriber_id, snapshot_id=event.snapshot_id
            )
        )


@domain.command_handler(part_of=Subscriber)
class SubscriberCommandHandler:
    @handle(ApplyProfileSnapshot)
    def apply_snapshot(self, command: ApplyProfileSnapshot):
        repo = current_domain.repository_for(Subscriber)
        subscriber = repo.get(command.subscriber_id)
        if command.snapshot_id in subscriber.applied_snapshot_ids:
            return  # This snapshot was already applied

        snapshot = current_domain.repository_for(ProfileSnapshot).get(
            command.snapshot_id
        )
        subscriber.update_contact(snapshot.email, snapshot.name)
        subscriber.change_plan(snapshot.tier, snapshot.seats)  # sets the tier
        subscriber.set_flags_for_tier()  # reads the tier
        subscriber.record_snapshot(command.snapshot_id)
        repo.add(subscriber)


# --8<-- [end:sync]
