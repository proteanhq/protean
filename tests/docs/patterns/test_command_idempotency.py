"""Run the examples on ``docs/patterns/command-idempotency.md``."""

import pytest

from protean import Engine, UnitOfWork
from protean.exceptions import DuplicateCommandError, ExpectedVersionError
from tests.docs.support import load_example
from tests.shared import REDIS_URI

pytestmark = pytest.mark.no_test_domain


# Layer 1: submission-level deduplication with the Redis idempotency store


def test_the_idempotency_store_is_off_without_redis_url(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    example = load_example("patterns/command-idempotency/001.py")
    domain = example.domain
    domain.init(traverse=False)
    with domain.domain_context():
        assert domain.config["idempotency"]["redis_url"] is None
        assert domain.idempotency_store.is_active is False


@pytest.fixture
def carts_with_redis(monkeypatch):
    # A database number of its own, so flushing it touches no other test's keys.
    monkeypatch.setenv("REDIS_URL", f"{REDIS_URI}/9")
    example = load_example("patterns/command-idempotency/001.py")
    domain = example.domain
    domain.init(traverse=False)
    with domain.domain_context():
        store = domain.idempotency_store
        # Without an active store every call would run the handler, and the
        # duplicate checks below would test nothing.
        assert store.is_active
        store.flush()
        domain.repository_for(example.Cart).add(example.Cart(cart_id="c-1"))
        yield example
        store.flush()


def _add_three(example, key, **kwargs):
    return example.domain.process(
        example.AddItemToCart(cart_id="c-1", product_id="X", quantity=3),
        asynchronous=False,
        idempotency_key=key,
        **kwargs,
    )


@pytest.mark.redis
def test_a_retry_with_the_same_key_returns_the_first_result(carts_with_redis):
    example = carts_with_redis

    first = _add_three(example, "req-abc")
    again = _add_three(example, "req-abc")

    assert first == 3
    assert again == first
    cart = example.domain.repository_for(example.Cart).get("c-1")
    assert cart.quantity == 3


@pytest.mark.redis
def test_a_new_key_is_a_new_request(carts_with_redis):
    example = carts_with_redis

    _add_three(example, "req-abc")
    second = _add_three(example, "req-def")

    assert second == 6
    assert example.domain.repository_for(example.Cart).get("c-1").quantity == 6


@pytest.mark.redis
def test_raise_on_duplicate_carries_the_original_result(carts_with_redis):
    example = carts_with_redis
    _add_three(example, "req-abc")

    with pytest.raises(DuplicateCommandError) as exc:
        _add_three(example, "req-abc", raise_on_duplicate=True)

    assert exc.value.original_result == 3
    assert example.domain.repository_for(example.Cart).get("c-1").quantity == 3


# Natural idempotency: set-based operations


def test_updating_the_email_twice_leaves_the_same_state():
    example = load_example("patterns/command-idempotency/002.py")
    domain = example.domain
    domain.init(traverse=False)
    with domain.domain_context():
        repo = domain.repository_for(example.User)
        repo.add(example.User(user_id="u-1", email="old@example.com"))
        command = example.UpdateEmail(user_id="u-1", new_email="new@example.com")

        domain.process(command, asynchronous=False)
        once = repo.get("u-1")
        domain.process(command, asynchronous=False)
        twice = repo.get("u-1")

        # The stored version still counts each save; the fields do not move.
        assert (once.user_id, once.email) == ("u-1", "new@example.com")
        assert (twice.user_id, twice.email) == (once.user_id, once.email)


# Create operations: check-then-act


@pytest.fixture
def orders():
    example = load_example("patterns/command-idempotency/003.py")
    domain = example.domain
    domain.init(traverse=False)
    with domain.domain_context():
        yield example


def _place(example, order_id, total):
    return example.domain.process(
        example.PlaceOrder(order_id=order_id, items=["book"], total=total),
        asynchronous=False,
    )


def test_a_repeated_place_order_creates_the_order_once(orders):
    assert _place(orders, "ord-42", 10.0) == "ord-42"
    assert _place(orders, "ord-42", 99.0) == "ord-42"

    repo = orders.domain.repository_for(orders.Order)
    placed = repo.query.all().items
    assert [order.order_id for order in placed] == ["ord-42"]
    assert repo.get("ord-42").total == 10.0


def test_a_different_order_id_creates_a_second_order(orders):
    _place(orders, "ord-42", 10.0)
    _place(orders, "ord-43", 20.0)

    repo = orders.domain.repository_for(orders.Order)
    assert sorted(o.order_id for o in repo.query.all().items) == ["ord-42", "ord-43"]


# Additive operations: track processed commands on the aggregate


@pytest.fixture
def carts():
    example = load_example("patterns/command-idempotency/004.py")
    domain = example.domain
    domain.init(traverse=False)
    with domain.domain_context():
        domain.repository_for(example.Cart).add(example.Cart(cart_id="c-1"))
        yield example


def _add(example, key):
    example.domain.process(
        example.AddItemToCart(cart_id="c-1", product_id="X", quantity=3),
        asynchronous=False,
        idempotency_key=key,
    )
    return example.domain.repository_for(example.Cart).get("c-1")


def test_the_same_key_adds_the_item_once(carts):
    # No Redis here: the aggregate's own list of keys is the only guard.
    assert carts.domain.idempotency_store.is_active is False

    _add(carts, "req-abc")
    cart = _add(carts, "req-abc")

    assert cart.quantity == 3
    assert cart.processed_commands == ["req-abc"]


def test_a_different_key_adds_the_item_again(carts):
    _add(carts, "req-abc")
    cart = _add(carts, "req-def")

    assert cart.quantity == 6
    assert cart.processed_commands == ["req-abc", "req-def"]


def test_without_a_key_every_call_adds_the_item(carts):
    _add(carts, None)
    cart = _add(carts, None)

    assert cart.quantity == 6
    assert cart.processed_commands == []


# Event-sourced aggregates: expected version


@pytest.fixture
def bank():
    example = load_example("patterns/command-idempotency/005.py")
    domain = example.domain
    domain.init(traverse=False)
    with domain.domain_context():
        domain.repository_for(example.BankAccount).add(example.BankAccount.open("a-1"))
        yield example


def test_a_copy_loaded_before_the_first_commit_fails_on_version(bank):
    repo = bank.domain.repository_for(bank.BankAccount)
    stale = repo.get("a-1")

    bank.domain.process(
        bank.DepositMoney(account_id="a-1", amount=10.0), asynchronous=False
    )

    with pytest.raises(ExpectedVersionError):
        with UnitOfWork():
            stale.raise_(bank.MoneyDeposited(account_id="a-1", amount=10.0))
            repo.add(stale)

    assert repo.get("a-1").balance == 10.0


def test_a_copy_that_arrives_after_the_first_commit_applies_again(bank):
    command = bank.DepositMoney(account_id="a-1", amount=10.0)

    bank.domain.process(command, asynchronous=False)
    bank.domain.process(command, asynchronous=False)

    repo = bank.domain.repository_for(bank.BankAccount)
    assert repo.get("a-1").balance == 20.0


# Cross-aggregate commands


@pytest.fixture
def transfers():
    example = load_example("patterns/command-idempotency/006.py")
    domain = example.domain
    domain.config["event_processing"] = "async"
    domain.init(traverse=False)
    with domain.domain_context():
        repo = domain.repository_for(example.Account)
        repo.add(example.Account(account_id="src", balance=100.0))
        repo.add(example.Account(account_id="dst", balance=0.0))
        yield example


def _transfer(example):
    example.domain.process(
        example.TransferMoney(
            transfer_id="tr-1", from_account="src", to_account="dst", amount=30.0
        ),
        asynchronous=False,
    )


def test_the_command_handler_changes_only_the_source_account(transfers):
    _transfer(transfers)

    repo = transfers.domain.repository_for(transfers.Account)
    assert repo.get("src").balance == 70.0
    assert repo.get("dst").balance == 0.0

    Engine(transfers.domain, test_mode=True).run()

    assert repo.get("dst").balance == 30.0
    assert repo.get("dst").credited_transfers == ["tr-1"]


def test_a_redelivered_money_debited_credits_the_target_once(transfers):
    _transfer(transfers)

    stream = f"{transfers.Account.meta_.stream_category}-src"
    messages = [
        m
        for m in transfers.domain.event_store.store.read(stream)
        if m.metadata.headers.type.endswith(".MoneyDebited.v1")
    ]
    assert len(messages) == 1
    [message] = messages
    transfers.CreditTargetAccount._handle(message)
    transfers.CreditTargetAccount._handle(message)

    target = transfers.domain.repository_for(transfers.Account).get("dst")
    assert target.balance == 30.0
    assert target.credited_transfers == ["tr-1"]


def test_a_repeated_transfer_debits_the_source_once(transfers):
    _transfer(transfers)
    _transfer(transfers)

    stream = f"{transfers.Account.meta_.stream_category}-src"
    debited = [
        m
        for m in transfers.domain.event_store.store.read(stream)
        if m.metadata.headers.type.endswith(".MoneyDebited.v1")
    ]
    assert len(debited) == 1

    Engine(transfers.domain, test_mode=True).run()

    repo = transfers.domain.repository_for(transfers.Account)
    assert repo.get("src").balance == 70.0
    assert repo.get("src").debited_transfers == ["tr-1"]
    assert repo.get("dst").balance == 30.0
