from datetime import datetime

from protean import current_domain
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.fields import DateTime, Float, Identifier, String


class User(BaseAggregate):
    email = String()
    name = String()

    @classmethod
    def register(cls, email: str, name: str):
        user = cls(email=email, name=name)
        user.raise_(Registered(user_id=user.id, email=email, name=name))
        return user


class Registered(BaseEvent):
    user_id = Identifier()
    email = String()
    name = String()


class LoggedIn(BaseEvent):
    user_id = Identifier()


class LoggedOut(BaseEvent):
    user_id = Identifier()


class Token(BaseProjection):
    key = Identifier(identifier=True)
    id = Identifier(required=True)
    email = String(required=True)


class FullUser(BaseProjection):
    email = String(identifier=True)
    name = String()


class NewUserReport(BaseProjection):
    email = String(identifier=True)
    name = String()
    registered_at = DateTime(default=datetime.now)


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
    user_id = Identifier()
    amount = Float()
    at = DateTime(default=datetime.now)

    @classmethod
    def transact(cls, user_id: Identifier, amount: float):
        transaction = cls(user_id=user_id, amount=amount)
        transaction.raise_(Transacted(user_id=user_id, amount=amount))
        return transaction


class Transacted(BaseEvent):
    user_id = Identifier()
    amount = Float()
    at = DateTime(default=datetime.now)


class Balances(BaseProjection):
    user_id = Identifier(identifier=True)
    name = String()
    balance = Float()


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
