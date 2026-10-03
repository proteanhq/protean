# --8<-- [start:full]
import json

from protean import Domain
from protean.fields import HasOne, String

domain = Domain(name="Authentication")


@domain.aggregate(fact_events=True)
class User:
    name: String(max_length=50, required=True)
    email: String(required=True)
    status: String(choices=["ACTIVE", "ARCHIVED"])

    account = HasOne("Account")


@domain.entity(part_of=User)
class Account:
    password_hash: String(max_length=512)


domain.init(traverse=False)
with domain.domain_context():
    user = User(name="John Doe", email="john.doe@example.com")

    # Persist the user
    domain.repository_for(User).add(user)

    event_message = domain.event_store.store.read(
        f"authentication::user-fact-{user.id}"
    )[0]
    event = event_message.to_domain_object()

    print(json.dumps(event.to_dict(), indent=4))

    """ Output:
    {
        "name": "John Doe",
        "email": "john.doe@example.com",
        "status": null,
        "id": "1c0d7a89-2fb1-4851-aede-f01558adbd55",
        "account": null,
        "_metadata": {
            "headers": {
                "id": "authentication::user-fact-1c0d7a89-2fb1-4851-aede-f01558adbd55-0.1",
                "time": "2026-10-03T18:12:18.530420+00:00",
                "type": "Authentication.UserFactEvent.v1",
                "stream": "authentication::user-fact-1c0d7a89-2fb1-4851-aede-f01558adbd55",
                "traceparent": null,
                "idempotency_key": null,
                "deadline": null
            },
            "envelope": {
                "specversion": "1.0",
                "checksum": "2ae1c1615f1f1714a44bec40a4505fdcc7325027abe17e86851ce3b709d1a12a"
            },
            "domain": {
                "fqn": "abc.UserFactEvent",
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
# --8<-- [end:full]
