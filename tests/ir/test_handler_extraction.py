"""Tests for IRBuilder handler, service, and repository extraction."""

import pytest

from protean.ir.builder import IRBuilder

from .elements import build_handler_test_domain, build_resilient_handler_test_domain


@pytest.fixture
def account_cluster():
    """Return the Account aggregate's cluster."""
    domain = build_handler_test_domain()
    ir = IRBuilder(domain).build()
    for cluster in ir["clusters"].values():
        if cluster["aggregate"]["name"] == "Account":
            return cluster
    pytest.fail("Account cluster not found")


@pytest.fixture
def resilient_order_cluster():
    """Return the Order aggregate's cluster from the resilient handler domain."""
    domain = build_resilient_handler_test_domain()
    ir = IRBuilder(domain).build()
    for cluster in ir["clusters"].values():
        if cluster["aggregate"]["name"] == "Order":
            return cluster
    pytest.fail("Order cluster not found")


@pytest.mark.no_test_domain
class TestCommandHandlerExtraction:
    """Verify command handler IR dict structure."""

    def test_command_handler_present(self, account_cluster):
        assert len(account_cluster["command_handlers"]) == 1

    def test_element_type(self, account_cluster):
        ch = next(iter(account_cluster["command_handlers"].values()))
        assert ch["element_type"] == "COMMAND_HANDLER"

    def test_name(self, account_cluster):
        ch = next(iter(account_cluster["command_handlers"].values()))
        assert ch["name"] == "AccountCommandHandler"

    def test_part_of(self, account_cluster):
        ch = next(iter(account_cluster["command_handlers"].values()))
        agg_fqn = account_cluster["aggregate"]["fqn"]
        assert ch["part_of"] == agg_fqn

    def test_stream_category(self, account_cluster):
        ch = next(iter(account_cluster["command_handlers"].values()))
        assert ch["stream_category"] is not None
        assert ":command" in ch["stream_category"]

    def test_handlers_map(self, account_cluster):
        ch = next(iter(account_cluster["command_handlers"].values()))
        assert len(ch["handlers"]) >= 1
        # Handler values should be sorted lists of method names
        for methods in ch["handlers"].values():
            assert isinstance(methods, list)
            assert methods == sorted(methods)

    def test_subscription_structure(self, account_cluster):
        ch = next(iter(account_cluster["command_handlers"].values()))
        sub = ch["subscription"]
        assert "config" in sub
        assert "profile" in sub
        assert "type" in sub

    def test_keys_sorted(self, account_cluster):
        ch = next(iter(account_cluster["command_handlers"].values()))
        keys = list(ch.keys())
        assert keys == sorted(keys)


@pytest.mark.no_test_domain
class TestEventHandlerExtraction:
    """Verify event handler IR dict structure."""

    def test_event_handler_present(self, account_cluster):
        assert len(account_cluster["event_handlers"]) == 1

    def test_element_type(self, account_cluster):
        eh = next(iter(account_cluster["event_handlers"].values()))
        assert eh["element_type"] == "EVENT_HANDLER"

    def test_name(self, account_cluster):
        eh = next(iter(account_cluster["event_handlers"].values()))
        assert eh["name"] == "AccountEventHandler"

    def test_part_of(self, account_cluster):
        eh = next(iter(account_cluster["event_handlers"].values()))
        agg_fqn = account_cluster["aggregate"]["fqn"]
        assert eh["part_of"] == agg_fqn

    def test_source_stream(self, account_cluster):
        eh = next(iter(account_cluster["event_handlers"].values()))
        assert "source_stream" in eh

    def test_stream_category(self, account_cluster):
        eh = next(iter(account_cluster["event_handlers"].values()))
        assert eh["stream_category"] is not None

    def test_handlers_map(self, account_cluster):
        eh = next(iter(account_cluster["event_handlers"].values()))
        assert len(eh["handlers"]) >= 1

    def test_subscription_structure(self, account_cluster):
        eh = next(iter(account_cluster["event_handlers"].values()))
        sub = eh["subscription"]
        assert "config" in sub
        assert "profile" in sub
        assert "type" in sub

    def test_keys_sorted(self, account_cluster):
        eh = next(iter(account_cluster["event_handlers"].values()))
        keys = list(eh.keys())
        assert keys == sorted(keys)


@pytest.mark.no_test_domain
class TestCommandHandlerResilienceInIR:
    """Verify that command handler resilience options appear in the IR."""

    def test_resilience_present(self, resilient_order_cluster):
        ch = next(iter(resilient_order_cluster["command_handlers"].values()))
        assert "resilience" in ch

    def test_timeout_in_seconds(self, resilient_order_cluster):
        ch = next(iter(resilient_order_cluster["command_handlers"].values()))
        assert ch["resilience"]["timeout"] == 900.0

    def test_retries(self, resilient_order_cluster):
        ch = next(iter(resilient_order_cluster["command_handlers"].values()))
        assert ch["resilience"]["retries"] == 3

    def test_backoff(self, resilient_order_cluster):
        ch = next(iter(resilient_order_cluster["command_handlers"].values()))
        assert ch["resilience"]["backoff"] == "exponential"

    def test_retry_exceptions_sorted(self, resilient_order_cluster):
        ch = next(iter(resilient_order_cluster["command_handlers"].values()))
        exc_list = ch["resilience"]["retry_exceptions"]
        assert len(exc_list) == 2
        assert exc_list == sorted(exc_list)
        assert "builtins.ValueError" in exc_list
        assert "myapp.errors.TransientError" in exc_list

    def test_resilience_keys_sorted(self, resilient_order_cluster):
        ch = next(iter(resilient_order_cluster["command_handlers"].values()))
        keys = list(ch["resilience"].keys())
        assert keys == sorted(keys)

    def test_handler_keys_still_sorted(self, resilient_order_cluster):
        ch = next(iter(resilient_order_cluster["command_handlers"].values()))
        keys = list(ch.keys())
        assert keys == sorted(keys)


@pytest.mark.no_test_domain
class TestEventHandlerResilienceInIR:
    """Verify that event handler resilience options appear in the IR."""

    def test_resilience_present(self, resilient_order_cluster):
        eh = next(iter(resilient_order_cluster["event_handlers"].values()))
        assert "resilience" in eh

    def test_no_timeout_for_event_handler(self, resilient_order_cluster):
        eh = next(iter(resilient_order_cluster["event_handlers"].values()))
        assert "timeout" not in eh["resilience"]

    def test_retries(self, resilient_order_cluster):
        eh = next(iter(resilient_order_cluster["event_handlers"].values()))
        assert eh["resilience"]["retries"] == 5

    def test_backoff(self, resilient_order_cluster):
        eh = next(iter(resilient_order_cluster["event_handlers"].values()))
        assert eh["resilience"]["backoff"] == "linear"

    def test_retry_exceptions(self, resilient_order_cluster):
        eh = next(iter(resilient_order_cluster["event_handlers"].values()))
        assert eh["resilience"]["retry_exceptions"] == ["builtins.RuntimeError"]

    def test_handler_keys_still_sorted(self, resilient_order_cluster):
        eh = next(iter(resilient_order_cluster["event_handlers"].values()))
        keys = list(eh.keys())
        assert keys == sorted(keys)


@pytest.mark.no_test_domain
class TestHandlerResilienceOmittedWhenDefault:
    """Verify that handlers without resilience options omit the key."""

    def test_command_handler_no_resilience_key(self, account_cluster):
        ch = next(iter(account_cluster["command_handlers"].values()))
        assert "resilience" not in ch

    def test_event_handler_no_resilience_key(self, account_cluster):
        eh = next(iter(account_cluster["event_handlers"].values()))
        assert "resilience" not in eh


@pytest.mark.no_test_domain
class TestHandlerTimeoutAsSeconds:
    """Verify a numeric-seconds timeout is captured in the IR."""

    def test_numeric_timeout_captured_as_float(self):
        from protean import Domain, handle
        from protean.fields.simple import Identifier, String
        from protean.ir.builder import IRBuilder

        domain = Domain(name="NumericTimeoutTest", root_path=".")

        @domain.command(part_of="Order")
        class PlaceOrder:
            order_id = Identifier(required=True)

        @domain.aggregate
        class Order:
            customer_name = String(max_length=100, required=True)

        @domain.command_handler(part_of=Order, timeout=30)
        class OrderCommandHandler:
            @handle(PlaceOrder)
            def handle_place_order(self, command):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        for cluster in ir["clusters"].values():
            for ch in cluster["command_handlers"].values():
                if ch["name"] == "OrderCommandHandler":
                    assert ch["resilience"]["timeout"] == 30.0
                    assert isinstance(ch["resilience"]["timeout"], float)
                    return
        pytest.fail("OrderCommandHandler not found")


@pytest.mark.no_test_domain
class TestHandlerRetryExceptionInstanceEntry:
    """A misconfigured non-class retry_exceptions entry must not crash the IR."""

    def test_instance_entry_serialized_as_class_fqn(self):
        from protean import Domain, handle
        from protean.fields.simple import Identifier, String
        from protean.ir.builder import IRBuilder

        domain = Domain(name="RetryInstanceTest", root_path=".")

        @domain.command(part_of="Order")
        class PlaceOrder:
            order_id = Identifier(required=True)

        @domain.aggregate
        class Order:
            customer_name = String(max_length=100, required=True)

        # An exception *instance* rather than its class — a misconfiguration
        # that previously raised an opaque AttributeError from fqn().
        @domain.command_handler(part_of=Order, retry_exceptions=[ValueError("boom")])
        class OrderCommandHandler:
            @handle(PlaceOrder)
            def handle_place_order(self, command):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        for cluster in ir["clusters"].values():
            for ch in cluster["command_handlers"].values():
                if ch["name"] == "OrderCommandHandler":
                    assert ch["resilience"]["retry_exceptions"] == [
                        "builtins.ValueError"
                    ]
                    return
        pytest.fail("OrderCommandHandler not found")


@pytest.mark.no_test_domain
class TestApplicationServiceExtraction:
    """Verify application service IR dict structure."""

    def test_app_service_present(self, account_cluster):
        assert len(account_cluster["application_services"]) == 1

    def test_element_type(self, account_cluster):
        svc = next(iter(account_cluster["application_services"].values()))
        assert svc["element_type"] == "APPLICATION_SERVICE"

    def test_part_of(self, account_cluster):
        svc = next(iter(account_cluster["application_services"].values()))
        agg_fqn = account_cluster["aggregate"]["fqn"]
        assert svc["part_of"] == agg_fqn

    def test_keys_sorted(self, account_cluster):
        svc = next(iter(account_cluster["application_services"].values()))
        keys = list(svc.keys())
        assert keys == sorted(keys)


@pytest.mark.no_test_domain
class TestRepositoryExtraction:
    """Verify repository IR dict structure."""

    def test_repository_present(self, account_cluster):
        assert len(account_cluster["repositories"]) >= 1

    def test_element_type(self, account_cluster):
        for repo in account_cluster["repositories"].values():
            assert repo["element_type"] == "REPOSITORY"

    def test_part_of(self, account_cluster):
        agg_fqn = account_cluster["aggregate"]["fqn"]
        for repo in account_cluster["repositories"].values():
            assert repo["part_of"] == agg_fqn

    def test_keys_sorted(self, account_cluster):
        for repo in account_cluster["repositories"].values():
            keys = list(repo.keys())
            assert keys == sorted(keys)

    def test_database_omitted_when_default(self, account_cluster):
        """Repositories with default database='ALL' should not have a database key."""
        for repo in account_cluster["repositories"].values():
            assert "database" not in repo


@pytest.mark.no_test_domain
class TestRepositoryDatabaseOption:
    """Verify repository database option is captured in IR."""

    def test_non_default_database_captured(self):
        """Repository with explicit database option should have it in IR."""
        from protean import Domain
        from protean.fields.simple import String
        from protean.ir.builder import IRBuilder

        domain = Domain(name="RepoDbTest", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.repository(part_of=Order, database="memory")
        class OrderMemoryRepository:
            pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        for cluster in ir["clusters"].values():
            for repo in cluster["repositories"].values():
                if repo["name"] == "OrderMemoryRepository":
                    assert repo["database"] == "memory"
                    return
        pytest.fail("OrderMemoryRepository not found")
