import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.subscriber import BaseSubscriber
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils import fqn
from protean.utils.mixins import handle


class UserRegistered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()


class OrderPlaced(BaseEvent):
    id = Identifier()
    user_id = Identifier()
    amount = String()


class User(BaseAggregate):
    email = String()
    name = String()


class Order(BaseAggregate):
    user_id = Identifier()
    amount = String()


class UserSubscriber(BaseSubscriber):
    """First test subscriber for consumer group tests"""

    @handle(UserRegistered)
    def handle_user_registered(self, event: UserRegistered) -> None:
        pass


class OrderSubscriber(BaseSubscriber):
    """Second test subscriber for consumer group tests"""

    @handle(OrderPlaced)
    def handle_order_placed(self, event: OrderPlaced) -> None:
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Order)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(UserSubscriber, stream="user")
    test_domain.register(OrderSubscriber, stream="order")
    test_domain.init(traverse=False)


class TestConsumerGroupCreation:
    """Test consumer group creation functionality"""

    @pytest.mark.simple_queuing
    def test_consumer_group_created_on_engine_initialization(self, test_domain):
        """Test that consumer groups are created when engine is initialized"""
        Engine(test_domain, test_mode=True)

        # Access the default broker
        default_broker = test_domain.brokers["default"]

        # Check that consumer groups were created
        info = default_broker.info()
        assert "consumer_groups" in info

        # Should have groups for both subscribers
        consumer_groups = info["consumer_groups"]
        assert len(consumer_groups) >= 2

        # Check that groups were created for the subscribers
        user_subscriber_fqn = fqn(UserSubscriber)
        order_subscriber_fqn = fqn(OrderSubscriber)

        assert user_subscriber_fqn in consumer_groups
        assert order_subscriber_fqn in consumer_groups

    @pytest.mark.simple_queuing
    def test_consumer_group_structure(self, test_domain):
        """Test that consumer groups have the correct structure"""
        Engine(test_domain, test_mode=True)

        default_broker = test_domain.brokers["default"]
        info = default_broker.info()

        user_subscriber_fqn = fqn(UserSubscriber)
        group_info = info["consumer_groups"][user_subscriber_fqn]

        # Check structure
        assert "consumers" in group_info
        assert "created_at" in group_info
        assert "consumer_count" in group_info
        assert isinstance(group_info["consumers"], list)
        assert isinstance(group_info["consumer_count"], int)
        assert group_info["consumer_count"] == 0  # No active consumers yet

    @pytest.mark.simple_queuing
    def test_multiple_engines_create_same_groups(self, test_domain):
        """Test that multiple engines create the same consumer groups"""
        Engine(test_domain, test_mode=True)
        Engine(test_domain, test_mode=True)

        default_broker = test_domain.brokers["default"]
        info = default_broker.info()

        # Should still have the same groups (idempotent behavior)
        consumer_groups = info["consumer_groups"]
        user_subscriber_fqn = fqn(UserSubscriber)
        order_subscriber_fqn = fqn(OrderSubscriber)

        assert user_subscriber_fqn in consumer_groups
        assert order_subscriber_fqn in consumer_groups

    @pytest.mark.simple_queuing
    def test_consumer_group_names_use_subscriber_fqn(self, test_domain):
        """Test that consumer group names use the subscriber's fully qualified name"""
        Engine(test_domain, test_mode=True)

        default_broker = test_domain.brokers["default"]
        info = default_broker.info()

        # Check that group names are FQNs
        user_subscriber_fqn = fqn(UserSubscriber)
        order_subscriber_fqn = fqn(OrderSubscriber)

        assert user_subscriber_fqn in info["consumer_groups"]
        assert order_subscriber_fqn in info["consumer_groups"]

        # Verify FQN format (should contain module and class name)
        assert "test_consumer_group_creation" in user_subscriber_fqn
        assert "UserSubscriber" in user_subscriber_fqn
        assert "test_consumer_group_creation" in order_subscriber_fqn
        assert "OrderSubscriber" in order_subscriber_fqn

    @pytest.mark.simple_queuing
    def test_broker_info_method_returns_consistent_data(self, test_domain):
        """Test that broker.info() returns consistent data across calls"""
        Engine(test_domain, test_mode=True)

        default_broker = test_domain.brokers["default"]

        info1 = default_broker.info()
        info2 = default_broker.info()

        # Should be identical
        assert info1 == info2

        # Check specific group data consistency
        user_subscriber_fqn = fqn(UserSubscriber)
        group1 = info1["consumer_groups"][user_subscriber_fqn]
        group2 = info2["consumer_groups"][user_subscriber_fqn]

        assert group1["created_at"] == group2["created_at"]
        assert group1["consumer_count"] == group2["consumer_count"]

    @pytest.mark.simple_queuing
    def test_ensure_group_is_idempotent(self, test_domain):
        """Test that _ensure_group is idempotent"""
        Engine(test_domain, test_mode=True)

        default_broker = test_domain.brokers["default"]

        # Get initial info
        info_before = default_broker.info()
        user_subscriber_fqn = fqn(UserSubscriber)
        created_at_before = info_before["consumer_groups"][user_subscriber_fqn][
            "created_at"
        ]

        # Call _ensure_group again
        default_broker._ensure_group(user_subscriber_fqn, "user")

        # Check that nothing changed
        info_after = default_broker.info()
        created_at_after = info_after["consumer_groups"][user_subscriber_fqn][
            "created_at"
        ]

        assert created_at_before == created_at_after

    @pytest.mark.simple_queuing
    def test_different_subscribers_create_different_groups(self, test_domain):
        """Test that different subscribers create different consumer groups"""
        Engine(test_domain, test_mode=True)

        default_broker = test_domain.brokers["default"]
        info = default_broker.info()

        user_subscriber_fqn = fqn(UserSubscriber)
        order_subscriber_fqn = fqn(OrderSubscriber)

        # Should have separate groups
        assert user_subscriber_fqn != order_subscriber_fqn
        assert user_subscriber_fqn in info["consumer_groups"]
        assert order_subscriber_fqn in info["consumer_groups"]

        # Groups should have independent data
        user_group = info["consumer_groups"][user_subscriber_fqn]
        order_group = info["consumer_groups"][order_subscriber_fqn]

        # They may have different creation times
        assert "created_at" in user_group
        assert "created_at" in order_group

    @pytest.mark.simple_queuing
    def test_data_reset_clears_consumer_groups(self, test_domain):
        """Test that _data_reset clears consumer groups"""
        Engine(test_domain, test_mode=True)

        default_broker = test_domain.brokers["default"]

        # Verify groups exist
        info_before = default_broker.info()
        assert len(info_before["consumer_groups"]) > 0

        # Reset data
        default_broker._data_reset()

        # Verify groups are cleared
        info_after = default_broker.info()
        assert len(info_after["consumer_groups"]) == 0
