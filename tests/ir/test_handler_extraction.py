"""Tests for IRBuilder handler, service, and repository extraction."""

import pytest

from protean.ir.builder import IRBuilder

from .elements import build_handler_test_domain


@pytest.fixture
def account_cluster():
    """Return the Account aggregate's cluster."""
    domain = build_handler_test_domain()
    ir = IRBuilder(domain).build()
    for _key, cluster in ir["clusters"].items():
        if cluster["aggregate"]["name"] == "Account":
            return cluster
    pytest.fail("Account cluster not found")


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
