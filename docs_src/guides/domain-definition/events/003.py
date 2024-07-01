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
            "id": "__main__.User.v1.e6bb751f-1304-4609-b1ff-b0ffad8e01ad.0.1",
            "timestamp": "2024-06-30 19:41:15.997664+00:00",
            "version": "v1",
            "sequence_id": "0.1",
            "payload_hash": 2404640527973230107
        },
        "_version": 0,
        "name": "John Doe",
        "email": "john.doe@example.com",
        "status": null,
        "account": null,
        "id": "e6bb751f-1304-4609-b1ff-b0ffad8e01ad"
    }
    """
