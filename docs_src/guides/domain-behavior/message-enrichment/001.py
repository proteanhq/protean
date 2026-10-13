from protean import Domain, handle
from protean.fields import Identifier, String
from protean.utils.globals import g

domain = Domain()


def get_current_user():
    return g.get("current_user")


def get_current_tenant_id():
    return g.get("tenant_id")


def get_client_ip():
    return g.get("client_ip")


def get_request_id():
    return g.get("request_id")


@domain.event(part_of="User")
class UserRegistered:
    user_id: Identifier(required=True)
    email: String(required=True)


@domain.aggregate
class User:
    email: String(required=True)

    def register(self):
        self.raise_(UserRegistered(user_id=self.id, email=self.email))


@domain.command(part_of=User)
class RegisterUser:
    user_id: Identifier(identifier=True)
    email: String(required=True)


@domain.command_handler(part_of=User)
class UserCommandHandler:
    @handle(RegisterUser)
    def register_user(self, command):
        pass


# --8<-- [start:functional]
# Functional registration
def add_user_context(event, aggregate):
    """Enrich every event with the current user."""
    user = get_current_user()
    return {
        "user_id": user.id if user else "system",
        "tenant_id": get_current_tenant_id(),
    }


domain.register_event_enricher(add_user_context)
# --8<-- [end:functional]


# --8<-- [start:decorator]
# Decorator registration
@domain.event_enricher
def add_audit_context(event, aggregate):
    return {"ip_address": get_client_ip()}


# --8<-- [end:decorator]


# --8<-- [start:command]
@domain.command_enricher
def add_request_context(command):
    return {
        "request_id": get_request_id(),
        "ip_address": get_client_ip(),
    }


# --8<-- [end:command]


# --8<-- [start:extensions]
def show_extensions(user):
    user.register()
    event = user._events[0]
    print(event._metadata.extensions)
    # {"user_id": "u-123", "tenant_id": "acme-corp", "ip_address": "10.0.0.1"}


# --8<-- [end:extensions]


# --8<-- [start:round_trip]
from protean.utils.eventing import Message


def round_trip(event):
    message = Message.from_domain_object(event)
    msg_dict = message.to_dict()
    print(msg_dict["metadata"]["extensions"])
    # {"user_id": "u-123", "tenant_id": "acme-corp", "ip_address": "10.0.0.1"}

    # Deserialize back
    restored = Message.deserialize(msg_dict)
    print(restored.metadata.extensions)
    # {"user_id": "u-123", "tenant_id": "acme-corp", "ip_address": "10.0.0.1"}


# --8<-- [end:round_trip]
