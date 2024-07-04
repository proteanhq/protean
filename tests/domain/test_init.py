from mock import Mock, patch

from protean.adapters.broker import Brokers
from protean.adapters.cache import Caches
from protean.adapters.event_store import EventStore
from protean.adapters.repository import Providers


class TestDomainInitMethodCalls:
    def test_domain_init_calls_validate_domain(self, test_domain):
        mock_validate_domain = Mock()
        test_domain._validate_domain = mock_validate_domain
        test_domain.init(traverse=False)
        mock_validate_domain.assert_called_once()

    def test_domain_init_calls_traverse(self, test_domain):
        mock_traverse = Mock()
        test_domain._traverse = mock_traverse
        test_domain.init()
        mock_traverse.assert_called_once()

    def test_domain_init_does_not_call_traverse_when_false(self, test_domain):
        mock_traverse = Mock()
        test_domain._traverse = mock_traverse
        test_domain.init(traverse=False)
        mock_traverse.assert_not_called()

    def test_domain_init_calls_resolve_references(self, test_domain):
        mock_resolve_references = Mock()
        test_domain._resolve_references = mock_resolve_references
        test_domain.init(traverse=False)
        mock_resolve_references.assert_called_once()

    def test_domain_init_constructs_fact_events(self, test_domain):
        mock_generate_fact_event_classes = Mock()
        test_domain._generate_fact_event_classes = mock_generate_fact_event_classes
        test_domain.init(traverse=False)
        mock_generate_fact_event_classes.assert_called_once()


class TestDomainInitializationCalls:
    @patch.object(Providers, "_initialize")
    def test_domain_initializes_providers(self, mock_initialize, test_domain):
        test_domain._initialize()
        mock_initialize.assert_called_once()

    @patch.object(Brokers, "_initialize")
    def test_domain_initializes_brokers(self, mock_initialize, test_domain):
        test_domain._initialize()
        mock_initialize.assert_called_once()

    @patch.object(Caches, "_initialize")
    def test_domain_initializes_caches(self, mock_initialize, test_domain):
        test_domain._initialize()
        mock_initialize.assert_called_once()

    @patch.object(EventStore, "_initialize")
    def test_domain_initializes_event_store(self, mock_initialize, test_domain):
        test_domain._initialize()
        mock_initialize.assert_called_once()
