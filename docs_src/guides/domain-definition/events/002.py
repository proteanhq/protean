import json
from datetime import datetime, timezone

from protean import BaseEvent, Domain
from protean.fields import DateTime, Identifier, String

domain = Domain(__name__)


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
            "id": "__main__.User.v1.1.0.1",
            "timestamp": "2024-06-30 16:29:31.312727+00:00",
            "version": "v1",
            "sequence_id": "0.1",
            "payload_hash": -7433283101704735063
        },
        "user_id": "1"
    }
    """

    user.activate()
    print(json.dumps(user._events[1].to_dict(), indent=4))

    """ Output:
    {
        "_metadata": {
            "id": "__main__.User.v2.1.0.2",
            "timestamp": "2024-06-30 16:32:59.703965+00:00",
            "version": "v2",
            "sequence_id": "0.2",
            "payload_hash": 7340170219237812824
        },
        "user_id": "1",
        "activated_at": "2024-06-30 16:32:59.704063+00:00"
    }
    """

    print(json.dumps(user._events[1].payload, indent=4))
