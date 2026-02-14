import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.subscriber import BaseSubscriber
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils import fqn
from protean.utils.mixins import handle


class User(BaseAggregate):
    email: String()
    name: String()


class Registered(BaseEvent):
    id: Identifier()
    email: String()
    name: String()


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def send_activation_email(self, event: Registered) -> None:
        pass


class DummyTestSubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.register(DummyTestSubscriber, stream="test_stream")
    test_domain.init(traverse=False)


@pytest.mark.asyncio
async def test_subscription_test_mode_branch_explicitly(test_domain):
    """Explicitly test the test_mode branch in Subscription.poll()"""
    engine = Engine(test_domain, test_mode=True)
    subscription = engine._subscriptions[fqn(UserEventHandler)]

    # Verify we're in test mode
    assert engine.test_mode is True

    # Create a direct poll scenario that will hit the test mode branch
    iteration_count = 0

    async def controlled_tick():
        nonlocal iteration_count
        iteration_count += 1
        # Allow a few iterations to ensure we hit the sleep branch
        if iteration_count >= 2:
            subscription.keep_going = False

    # Replace tick with our controlled version
    subscription.tick = controlled_tick

    # Run poll directly - this should hit the test mode branch
    await subscription.poll()

    # Verify we completed at least 2 iterations
    assert iteration_count >= 2


@pytest.mark.asyncio
async def test_broker_subscription_test_mode_branch_explicitly(test_domain):
    """Explicitly test the test_mode branch in BrokerSubscription.poll()"""
    engine = Engine(test_domain, test_mode=True)
    subscription = engine._broker_subscriptions[fqn(DummyTestSubscriber)]

    # Verify we're in test mode
    assert engine.test_mode is True

    # Create a direct poll scenario that will hit the test mode branch
    iteration_count = 0

    async def controlled_tick():
        nonlocal iteration_count
        iteration_count += 1
        # Allow a few iterations to ensure we hit the sleep branch
        if iteration_count >= 2:
            subscription.keep_going = False

    # Replace tick with our controlled version
    subscription.tick = controlled_tick

    # Run poll directly - this should hit the test mode branch
    await subscription.poll()

    # Verify we completed at least 2 iterations
    assert iteration_count >= 2


@pytest.mark.asyncio
async def test_subscription_non_test_mode_branch(test_domain):
    """Test the non-test_mode branch in Subscription.poll() for completeness"""
    engine = Engine(test_domain, test_mode=False)
    subscription = engine._subscriptions[fqn(UserEventHandler)]

    # Verify we're NOT in test mode
    assert engine.test_mode is False

    iteration_count = 0

    async def controlled_tick():
        nonlocal iteration_count
        iteration_count += 1
        # Stop quickly to avoid sleeping for the tick_interval
        if iteration_count >= 1:
            subscription.keep_going = False

    # Replace tick with our controlled version
    subscription.tick = controlled_tick

    # Set a very small tick_interval to minimize actual sleep time
    subscription.tick_interval = 0.001

    # Run poll directly
    await subscription.poll()

    # Verify we completed the iteration
    assert iteration_count >= 1


@pytest.mark.asyncio
async def test_broker_subscription_non_test_mode_branch(test_domain):
    """Test the non-test_mode branch in BrokerSubscription.poll() for completeness"""
    engine = Engine(test_domain, test_mode=False)
    subscription = engine._broker_subscriptions[fqn(DummyTestSubscriber)]

    # Verify we're NOT in test mode
    assert engine.test_mode is False

    iteration_count = 0

    async def controlled_tick():
        nonlocal iteration_count
        iteration_count += 1
        # Stop quickly to avoid sleeping for the tick_interval
        if iteration_count >= 1:
            subscription.keep_going = False

    # Replace tick with our controlled version
    subscription.tick = controlled_tick

    # Set a very small tick_interval to minimize actual sleep time
    subscription.tick_interval = 0.001

    # Run poll directly
    await subscription.poll()

    # Verify we completed the iteration
    assert iteration_count >= 1
