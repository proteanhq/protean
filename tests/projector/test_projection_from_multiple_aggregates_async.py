import asyncio

import pytest

from protean import current_domain
from protean.server import Engine

from .elements import (
    Balances,
    Registered,
    Transacted,
    Transaction,
    TransactionProjector,
    User,
)


@pytest.fixture(autouse=True)
def setup_test_domain(test_domain):
    test_domain.config["event_processing"] = "async"

    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Transaction)
    test_domain.register(Transacted, part_of=Transaction)
    test_domain.register(
        TransactionProjector, projector_for=Balances, aggregates=[Transaction, User]
    )
    test_domain.register(Balances)

    test_domain.init(traverse=False)


def test_balance_projection_for_new_user(test_domain):
    user = User.register(email="test@test.com", name="Test User")
    current_domain.repository_for(User).add(user)

    engine = Engine(domain=test_domain, test_mode=True)
    engine.run()

    balance = current_domain.repository_for(Balances).get(user.id)
    assert balance is not None
    assert balance.balance == 0


def test_balance_projection_for_transacted_user(test_domain):
    user = User.register(email="test@test.com", name="Test User")
    current_domain.repository_for(User).add(user)

    engine = Engine(domain=test_domain, test_mode=True)
    engine.run()

    balance = current_domain.repository_for(Balances).get(user.id)
    assert balance is not None
    assert balance.name == "Test User"
    assert balance.balance == 0

    # Create and set a new loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    transaction = Transaction.transact(user_id=user.id, amount=100)
    current_domain.repository_for(Transaction).add(transaction)

    engine = Engine(domain=test_domain, test_mode=True)
    engine.run()

    balance = current_domain.repository_for(Balances).get(user.id)
    assert balance is not None
    assert balance.name == "Test User"
    assert balance.balance == 100
