import json
from datetime import datetime, timezone

from protean import BaseEvent, Domain
from protean.fields import DateTime, Identifier, String

domain = Domain(__name__, name="Authentication")


@domain.aggregate
class User:
    id = Identifier(identifier=True)
    email = String()
    name = String()
    status = String(choices=["INACTIVE", "ACTIVE", "ARCHIVED"], default="INACTIVE")

    def login(self):
        self.raise_(UserLoggedIn(user_id=self.id))

    def activate(self):
        self.status = "ACTIVE"
        self.raise_(UserActivated(user_id=self.id))


@domain.event(part_of="User")
class UserLoggedIn(BaseEvent):
    user_id = Identifier(identifier=True)


@domain.event(part_of="User")
class UserActivated:
    __version__ = "v2"

    user_id = Identifier(required=True)
    activated_at = DateTime(required=True, default=lambda: datetime.now(timezone.utc))


domain.init(traverse=False)
with domain.domain_context():
    user = User(id="1", email="<EMAIL>", name="<NAME>")

    user.login()
    print(json.dumps(user._events[0].to_dict(), indent=4))

    """ Output:
    {
        "_metadata": {
            "id": "authentication::user-1-0.1",
            "type": "Authentication.UserLoggedIn.v1",
            "fqn": "__main__.UserLoggedIn",
            "kind": "EVENT",
            "stream": "authentication::user-1",
            "origin_stream": null,
            "timestamp": "2024-07-18 22:06:10.148226+00:00",
            "version": "v1",
            "sequence_id": "0.1",
            "payload_hash": 6154717103144054927
        },
        "user_id": "1"
    }
    """

    user.activate()
    print(json.dumps(user._events[1].to_dict(), indent=4))

    """ Output:
    {
        "_metadata": {
            "id": "authentication::user-1-0.2",
            "type": "Authentication.UserActivated.v2",
            "fqn": "__main__.UserActivated",
            "kind": "EVENT",
            "stream": "authentication::user-1",
            "origin_stream": null,
            "timestamp": "2024-07-18 22:06:10.155603+00:00",
            "version": "v2",
            "sequence_id": "0.2",
            "payload_hash": -3600345200911557224
        },
        "user_id": "1",
        "activated_at": "2024-07-18 22:06:10.155694+00:00"
    }
    """
