from protean import Domain
from protean.fields import Identifier, Integer, String, ValueObject

domain = Domain(__file__)


@domain.aggregate
class User:
    first_name = String(max_length=50)
    last_name = String(max_length=50)
    age = Integer()


@domain.value_object(aggregate_cls="Subscription")
class Subscriber:
    id = Identifier()
    full_name = String(max_length=102)


@domain.aggregate
class Subscription:
    plan = String(max_length=50)
    user = ValueObject(Subscriber)
    status = String(max_length=50)


@domain.aggregate
class Plan:
    name = String(max_length=50)
    price = Integer()


@domain.domain_service
class SubscriptionManagement:
    def subscribe_user(self, user, plan):
        subscription = Subscription(user=user, plan=plan, status="ACTIVE")
        return subscription
