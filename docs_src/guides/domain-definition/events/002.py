# --8<-- [start:full]
import json
from datetime import UTC, datetime

from protean import Domain
from protean.fields import DateTime, Identifier, String

domain = Domain(__name__, name="Authentication")


@domain.aggregate
class User:
    id: Identifier(identifier=True)
    email: String()
    name: String()
    status: String(choices=["INACTIVE", "ACTIVE", "ARCHIVED"], default="INACTIVE")

    def login(self):
        self.raise_(UserLoggedIn(user_id=self.id))

    def activate(self):
        self.status = "ACTIVE"
        self.raise_(UserActivated(user_id=self.id))


@domain.event(part_of="User")
class UserLoggedIn:
    user_id: Identifier(identifier=True)


@domain.event(part_of="User")
class UserActivated:
    __version__ = 2

    user_id: Identifier(required=True)
    activated_at: DateTime(default=lambda: datetime.now(UTC))


domain.init(traverse=False)
with domain.domain_context():
    user = User(id="1", email="<EMAIL>", name="<NAME>")

    user.login()
    print(json.dumps(user._events[0].to_dict(), indent=4))

    """ Output:
    {
        "user_id": "1",
        "_metadata": {
            "headers": {
                "id": "authentication::user-1-0.1",
                "time": "2026-10-07T03:40:39.873068+00:00",
                "type": "Authentication.UserLoggedIn.v1",
                "stream": "authentication::user-1",
                "traceparent": null,
                "idempotency_key": null,
                "deadline": null
            },
            "envelope": {
                "specversion": "1.0",
                "checksum": "cd9d7b681c5e44fab98ffa379db7c5ee5a143824dc235117339b54221ab2e2c8"
            },
            "domain": {
                "fqn": "__main__.UserLoggedIn",
                "kind": "EVENT",
                "origin_stream": null,
                "stream_category": "authentication::user",
                "version": 1,
                "sequence_id": "0.1",
                "asynchronous": true,
                "expected_version": null,
                "priority": 0,
                "correlation_id": null,
                "causation_id": null
            },
            "event_store": null,
            "extensions": {}
        }
    }
    """

    user.activate()
    print(json.dumps(user._events[1].to_dict(), indent=4))

    """ Output:
    {
        "user_id": "1",
        "activated_at": "2026-10-07T03:40:39.873535+00:00",
        "_metadata": {
            "headers": {
                "id": "authentication::user-1-0.2",
                "time": "2026-10-07T03:40:39.873555+00:00",
                "type": "Authentication.UserActivated.v2",
                "stream": "authentication::user-1",
                "traceparent": null,
                "idempotency_key": null,
                "deadline": null
            },
            "envelope": {
                "specversion": "1.0",
                "checksum": "3b7ed6cf91868701792caba1d9e948b0f3a5a47c74586b60f970cfeb32c8b12a"
            },
            "domain": {
                "fqn": "__main__.UserActivated",
                "kind": "EVENT",
                "origin_stream": null,
                "stream_category": "authentication::user",
                "version": 2,
                "sequence_id": "0.2",
                "asynchronous": true,
                "expected_version": null,
                "priority": 0,
                "correlation_id": null,
                "causation_id": null
            },
            "event_store": null,
            "extensions": {}
        }
    }
    """
# --8<-- [end:full]
