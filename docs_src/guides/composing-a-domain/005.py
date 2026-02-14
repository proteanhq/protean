from protean import Domain
from protean.fields import ValueObject
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class User:
    first_name: Annotated[str, Field(max_length=50)] | None = None
    last_name: Annotated[str, Field(max_length=50)] | None = None
    age: int | None = None


@domain.value_object(part_of="Subscription")
class Subscriber:
    id: str | None = None
    full_name: Annotated[str, Field(max_length=102)] | None = None


@domain.aggregate
class Subscription:
    plan: Annotated[str, Field(max_length=50)] | None = None
    user = ValueObject(Subscriber)
    status: Annotated[str, Field(max_length=50)] | None = None


@domain.aggregate
class Plan:
    name: Annotated[str, Field(max_length=50)] | None = None
    price: int | None = None


@domain.domain_service(part_of=[Subscription, Plan])
class SubscriptionManagement:
    def subscribe_user(self, user, plan):
        subscription = Subscription(user=user, plan=plan, status="ACTIVE")
        return subscription
