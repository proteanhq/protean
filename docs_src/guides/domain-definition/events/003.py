import json

from protean import Domain
from protean.fields import HasOne, String
from protean.utils.mixins import Message

domain = Domain(__file__, name="Authentication")


@domain.aggregate(fact_events=True)
class User:
    name = String(max_length=50, required=True)
    email = String(required=True)
    status = String(choices=["ACTIVE", "ARCHIVED"])

    account = HasOne("Account")


@domain.entity(part_of=User)
class Account:
    password_hash = String(max_length=512)


domain.init(traverse=False)
with domain.domain_context():
    user = User(name="John Doe", email="john.doe@example.com")

    # Persist the user
    domain.repository_for(User).add(user)

    event_message = domain.event_store.store.read(
        f"authentication::user-fact-{user.id}"
    )[0]
    event = Message.to_object(event_message)

    print(json.dumps(event.to_dict(), indent=4))

    """ Output:
    {
        "_metadata": {
            "id": "authentication::user-fact-781c4363-5e7e-4c53-a599-2cb2dc428d96-0.1",
            "type": "Authentication.UserFactEvent.v1",
            "fqn": "protean.container.UserFactEvent",
            "kind": "EVENT",
            "stream": "authentication::user-fact-781c4363-5e7e-4c53-a599-2cb2dc428d96",
            "origin_stream": null,
            "timestamp": "2024-07-18 22:01:02.364078+00:00",
            "version": "v1",
            "sequence_id": "0.1",
            "payload_hash": 2754382941688457931
        },
        "_version": 0,
        "name": "John Doe",
        "email": "john.doe@example.com",
        "status": null,
        "account": null,
        "id": "781c4363-5e7e-4c53-a599-2cb2dc428d96"
    }
    """
