import json

from protean import Domain
from protean.fields import HasOne, String
from protean.utils.mixins import Message

domain = Domain(__file__, load_toml=False)


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

    event_message = domain.event_store.store.read(f"user-fact-{user.id}")[0]
    event = Message.to_object(event_message)

    print(json.dumps(event.to_dict(), indent=4))

    """ Output:
    {
        "_metadata": {
            "id": "user-fact-e97cef08-f11d-43eb-8a69-251a0828bbff-0.1",
            "type": "User.UserFactEvent.v1",
            "kind": "EVENT",
            "stream_name": "user-fact-e97cef08-f11d-43eb-8a69-251a0828bbff",
            "origin_stream_name": null,
            "timestamp": "2024-07-09 17:24:41.800475+00:00",
            "version": "v1",
            "sequence_id": "0.1",
            "payload_hash": -1529271686230030119
        },
        "_version": 0,
        "name": "John Doe",
        "email": "john.doe@example.com",
        "status": null,
        "account": null,
        "id": "e97cef08-f11d-43eb-8a69-251a0828bbff"
    }
    """
