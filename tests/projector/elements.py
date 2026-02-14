from datetime import datetime

from pydantic import Field

from protean import current_domain
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None

    @classmethod
    def register(cls, email: str, name: str):
        user = cls(email=email, name=name)
        user.raise_(Registered(user_id=user.id, email=email, name=name))
        return user


class Registered(BaseEvent):
    user_id: str | None = None
    email: str | None = None
    name: str | None = None


class LoggedIn(BaseEvent):
    user_id: str | None = None


class LoggedOut(BaseEvent):
    user_id: str | None = None


class Token(BaseProjection):
    key: str = Field(json_schema_extra={"identifier": True})
    id: str
    email: str


class FullUser(BaseProjection):
    email: str = Field(json_schema_extra={"identifier": True})
    name: str | None = None


class NewUserReport(BaseProjection):
    email: str = Field(json_schema_extra={"identifier": True})
    name: str | None = None
    registered_at: datetime | None = Field(default_factory=datetime.now)


class TokenProjector(BaseProjector):
    @on(LoggedIn)
    def on_logged_in(self, event: LoggedIn):
        token = Token(id=event.user_id, email=event.email, key=event.key)
        current_domain.repository_for(Token).add(token)

    @on(LoggedIn)
    def on_logged_in_2(self, event: LoggedIn):
        """This is a dummy method to test that multiple handlers can be recorded against the same event"""
        pass

    @on(LoggedOut)
    def on_logged_out(self, event: LoggedOut):
        token = current_domain.repository_for(Token).get(event.user_id)
        current_domain.repository_for(Token).delete(token)


class FullUserProjector(BaseProjector):
    @on(Registered)
    def on_registered(self, event: Registered):
        pass

    @on(LoggedIn)
    def on_logged_in(self, event: LoggedIn):
        pass

    @on(LoggedOut)
    def on_logged_out(self, event: LoggedOut):
        pass


class NewUserProjector(BaseProjector):
    @on(Registered)
    def on_registered(self, event: Registered):
        pass


class Transaction(BaseAggregate):
    user_id: str | None = None
    amount: float | None = None
    at: datetime | None = Field(default_factory=datetime.now)

    @classmethod
    def transact(cls, user_id: str, amount: float):
        transaction = cls(user_id=user_id, amount=amount)
        transaction.raise_(Transacted(user_id=user_id, amount=amount))
        return transaction


class Transacted(BaseEvent):
    user_id: str | None = None
    amount: float | None = None
    at: datetime | None = Field(default_factory=datetime.now)


class Balances(BaseProjection):
    user_id: str = Field(json_schema_extra={"identifier": True})
    name: str | None = None
    balance: float | None = None


class TransactionProjector(BaseProjector):
    @on(Registered)
    def on_registered(self, event: Registered):
        balance = Balances(user_id=event.user_id, name=event.name, balance=0)
        current_domain.repository_for(Balances).add(balance)

    @on(Transacted)
    def on_transacted(self, event: Transacted):
        balance = current_domain.repository_for(Balances).get(event.user_id)
        if balance:
            balance.balance += event.amount
        else:
            balance = Balances(
                user_id=event.user_id, name=event.name, balance=event.amount
            )
        current_domain.repository_for(Balances).add(balance)
