"""The examples on ``docs/reference/configuration/index.md`` behave as the page says."""

import pytest

from protean import Domain
from protean.adapters.cache.redis import RedisCache
from protean.adapters.event_store.message_db import MessageDBStore
from protean.adapters.repository.sqlalchemy import SqliteProvider
from protean.exceptions import ConfigurationError
from protean.fields import String
from protean.ir.builder import validate_lint_table
from protean.ir.diagnostics import DiagnosticCode
from protean.server.subscription.config_resolver import ConfigResolver
from protean.server.subscription.profiles import SubscriptionType
from tests.docs.support import DOCS_SRC, load_example

pytestmark = pytest.mark.no_test_domain

EXAMPLES = DOCS_SRC / "reference/configuration/index"


@pytest.fixture
def no_env(monkeypatch):
    # The pytest plugin sets PROTEAN_ENV=test, which would apply a [test]
    # overlay. The base configuration is what these tests read first.
    monkeypatch.delenv("PROTEAN_ENV", raising=False)


@pytest.fixture
def load_toml(tmp_path, no_env):
    def load(name, domain_name="Config"):
        (tmp_path / "domain.toml").write_text((EXAMPLES / name).read_text())
        return Domain(root_path=str(tmp_path), name=domain_name)

    return load


# Direct configuration


def test_direct_config_sets_debug_and_testing():
    example = load_example("reference/configuration/index/001.py")

    assert example.domain.config["debug"] is True
    assert example.domain.config["testing"] is True
    # Keys not passed keep the framework defaults
    assert example.domain.config["event_processing"] == "async"
    assert example.domain.config["databases"]["default"] == {"provider": "memory"}


# The sample file and its environment overlays


def test_sample_base_values(load_toml):
    domain = load_toml("sample.toml")
    config = domain.config

    assert config["debug"] is True
    assert config["testing"] is True
    assert config["secret_key"] == "tvTpk3PAfkGr5x9!2sFU%XpW7bR8cwKA"
    assert config["identity_strategy"] == "uuid"
    assert config["identity_type"] == "string"
    assert config["event_processing"] == "sync"
    assert config["command_processing"] == "sync"
    assert config["databases"]["default"] == {"provider": "memory"}
    assert config["databases"]["memory"] == {"provider": "memory"}
    assert config["brokers"]["default"] == {"provider": "inline"}
    assert config["caches"]["default"]["provider"] == "memory"
    assert config["event_store"] == {"provider": "memory"}
    assert config["custom"] == {"foo": "bar"}
    assert domain.foo == "bar"
    assert config["telemetry"]["enabled"] is False


def test_sample_staging_overlay(load_toml, monkeypatch):
    monkeypatch.setenv("PROTEAN_ENV", "staging")
    domain = load_toml("sample.toml")
    config = domain.config

    assert config["event_processing"] == "async"
    assert config["command_processing"] == "sync"
    assert config["databases"]["default"] == {
        "provider": "sqlite",
        "database_uri": "sqlite:///test.db",
    }
    assert config["brokers"]["default"] == {
        "provider": "redis_pubsub",
        "URI": "redis://staging.example.com:6379/2",
    }
    assert domain.foo == "qux"


def test_sample_prod_overlay(load_toml, monkeypatch):
    monkeypatch.setenv("PROTEAN_ENV", "prod")
    domain = load_toml("sample.toml")
    config = domain.config

    assert config["event_processing"] == "async"
    assert config["command_processing"] == "async"
    assert config["databases"]["default"] == {
        "provider": "postgresql",
        "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
    }
    assert config["brokers"]["default"] == {
        "provider": "redis_pubsub",
        "URI": "redis://prod.example.com:6379/2",
    }
    assert config["event_store"] == {
        "provider": "message_db",
        "database_uri": "postgresql://message_store@localhost:5433/message_store",
    }
    assert domain.foo == "quux"
    assert config["telemetry"] == {
        "enabled": True,
        "service_name": "my-service",
        "exporter": "otlp",
        "endpoint": "http://otel-collector:4317",
        "resource_attributes": {},
    }


def test_env_key_does_not_select_an_overlay(tmp_path, no_env):
    (tmp_path / "domain.toml").write_text(
        'env = "prod"\n' + (EXAMPLES / "sample.toml").read_text()
    )
    domain = Domain(root_path=str(tmp_path), name="Config")

    assert domain.config["env"] == "prod"
    assert domain.config["command_processing"] == "sync"
    assert domain.foo == "bar"


# field_defaults


def _with_note(domain):
    @domain.aggregate
    class Note:
        body: String(max_length=100)

    domain.init(traverse=False)
    return Note


def test_field_defaults_sanitize_false_stores_raw_input(load_toml):
    domain = load_toml("field_defaults.toml")
    assert domain.config["field_defaults"] == {"sanitize": False}

    Note = _with_note(domain)
    with domain.domain_context():
        assert Note(body="<script>x</script>").body == "<script>x</script>"


def test_field_defaults_sanitize_true_cleans_unset_fields():
    domain = Domain(name="Config", config={"field_defaults": {"sanitize": True}})

    Note = _with_note(domain)
    with domain.domain_context():
        assert Note(body="<script>x</script>").body != "<script>x</script>"


def test_field_defaults_typo_is_rejected():
    with pytest.raises(ConfigurationError, match="must be a boolean") as exc:
        Domain(name="Config", config={"field_defaults": {"sanitize": "maybe"}})

    assert exc.value.code == DiagnosticCode.CONFIG_INVALID_FIELD_DEFAULTS


def test_field_defaults_empty_env_var_reads_as_false(tmp_path, no_env, monkeypatch):
    monkeypatch.delenv("SANITIZE", raising=False)
    (tmp_path / "domain.toml").write_text(
        '[field_defaults]\nsanitize = "${SANITIZE|}"\n'
    )
    domain = Domain(root_path=str(tmp_path), name="Config")

    assert domain.config["field_defaults"] == {"sanitize": ""}
    Note = _with_note(domain)
    with domain.domain_context():
        assert Note(body="<b>x</b>").body == "<b>x</b>"


# Adapters


def test_databases_and_provider_on_an_aggregate(load_toml, tmp_path, monkeypatch):
    domain = load_toml("databases.toml")
    assert domain.config["databases"] == {
        "default": {"provider": "memory"},
        "memory": {"provider": "memory"},
        "sqlite": {"provider": "sqlite", "database_uri": "sqlite:///test.db"},
    }

    example = load_example("reference/configuration/index/002.py")
    assert example.User.meta_.provider == "sqlite"

    # The relative sqlite path is resolved from the working directory
    monkeypatch.chdir(tmp_path)

    @domain.aggregate(provider="sqlite")
    class User:
        name: String(max_length=50)

    domain.init(traverse=False)
    with domain.domain_context():
        provider = domain.providers["sqlite"]
        assert isinstance(provider, SqliteProvider)
        assert domain.repository_for(User)._provider is provider


def test_caches_forward_pool_keys(load_toml):
    domain = load_toml("caches.toml")
    redis_conf = domain.config["caches"]["redis"]
    assert redis_conf == {
        "provider": "redis",
        "URI": "redis://127.0.0.1:6379/2",
        "TTL": 300,
        "max_connections": 50,
        "socket_timeout": 5,
        "socket_connect_timeout": 5,
        "retry_on_timeout": True,
    }
    assert domain.config["caches"]["default"]["provider"] == "memory"

    # Building the client does not connect to Redis
    cache = RedisCache("redis", domain, dict(redis_conf))
    pool = cache.r.connection_pool
    assert pool.max_connections == 50
    assert pool.connection_kwargs["socket_timeout"] == 5
    assert pool.connection_kwargs["socket_connect_timeout"] == 5
    assert pool.connection_kwargs["retry_on_timeout"] is True


def test_brokers_keep_provider_names_and_key_casing(load_toml):
    domain = load_toml("brokers.toml")

    assert domain.config["brokers"] == {
        "default": {"provider": "inline"},
        "redis": {
            "provider": "redis",
            "URI": "redis://127.0.0.1:6379/0",
            "max_connections": 50,
            "socket_timeout": 5,
            "socket_connect_timeout": 5,
            "retry_on_timeout": True,
        },
    }


def test_event_store_forwards_max_connections(load_toml):
    domain = load_toml("event_store.toml")
    conf = domain.config["event_store"]
    assert conf == {
        "provider": "message_db",
        "database_uri": "postgresql://message_store@localhost:5433/message_store",
        "max_connections": 20,
    }

    # The pool is opened lazily, on first use
    store = MessageDBStore(domain, dict(conf))
    assert store._pool_kwargs == {"max_connections": 20}


# [server]


def test_server_values(load_toml):
    domain = load_toml("server.toml")
    server = domain.config["server"]

    assert server["default_subscription_type"] == "stream"
    assert server["default_subscription_profile"] == "production"
    assert server["messages_per_tick"] == 100
    assert server["drain_timeout"] == 10
    assert server["stream_subscription"] == {
        "blocking_timeout_ms": 5000,
        "max_retries": 3,
        "retry_delay_seconds": 1,
        "enable_dlq": True,
    }
    assert server["event_store_subscription"] == {
        "position_update_interval": 10,
        "max_retries": 3,
        "retry_delay_seconds": 1,
        "enable_recovery": True,
        "recovery_interval_seconds": 30,
        "gap_timeout_seconds": 5,
    }
    assert server["broker_subscription"] == {
        "max_retries": 3,
        "retry_delay_seconds": 1,
        "enable_dlq": True,
    }
    assert server["version_retry"] == {
        "enabled": True,
        "max_retries": 3,
        "base_delay_seconds": 0.05,
        "max_delay_seconds": 1.0,
    }
    assert server["transient_retry"] == {
        "enabled": False,
        "max_retries": 3,
        "backoff": "exponential",
        "base_delay_seconds": 0.1,
        "max_delay_seconds": 5.0,
        "exceptions": [
            "builtins.ConnectionError",
            "builtins.TimeoutError",
            "protean.exceptions.SendError",
        ],
    }
    assert server["dlq"] == {
        "enabled": False,
        "retention_hours": 168,
        "alert_threshold": 100,
        "check_interval_seconds": 60,
        "alert_callback": "myapp.alerts.notify_oncall",
    }
    assert server["health"] == {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8080,
        "port_auto_increment": False,
    }
    assert server["priority_lanes"] == {
        "enabled": False,
        "threshold": 0,
        "backfill_suffix": "backfill",
    }
    assert server["subscriptions"] == {
        "OrderEventHandler": {
            "profile": "fast",
            "messages_per_tick": 50,
            "dlq_retention_hours": 72,
            "dlq_alert_threshold": 25,
        },
        "InventoryProjector": {
            "subscription_type": "event_store",
            "profile": "projection",
        },
    }
    # A stream default subscription turns the outbox on
    assert domain.has_outbox is True


def test_server_handler_overrides_resolve(load_toml):
    domain = load_toml("server.toml")
    resolver = ConfigResolver(domain)

    class OrderEventHandler:
        pass

    class InventoryProjector:
        pass

    order = resolver.resolve(OrderEventHandler)
    # The `fast` profile sets these, over the server-wide defaults
    assert order.subscription_type == SubscriptionType.STREAM
    assert order.blocking_timeout_ms == 100
    assert order.max_retries == 2
    # The handler's own keys win over the profile
    assert order.messages_per_tick == 50

    inventory = resolver.resolve(InventoryProjector)
    assert inventory.subscription_type == SubscriptionType.EVENT_STORE
    assert inventory.enable_dlq is False


@pytest.mark.xfail(
    strict=True,
    reason=(
        "ConfigResolver builds SubscriptionConfig from a field list that leaves "
        "out dlq_retention_hours and dlq_alert_threshold, so the per-handler "
        "DLQ overrides are dropped"
    ),
)
def test_server_per_handler_dlq_overrides_resolve(load_toml):
    domain = load_toml("server.toml")

    class OrderEventHandler:
        pass

    order = ConfigResolver(domain).resolve(OrderEventHandler)

    assert order.dlq_retention_hours == 72
    assert order.dlq_alert_threshold == 25


def test_outbox_values(load_toml):
    domain = load_toml("outbox.toml")
    outbox = domain.config["outbox"]

    assert domain.config["server"]["default_subscription_type"] == "stream"
    assert domain.has_outbox is True
    assert outbox["broker"] == "default"
    assert outbox["messages_per_tick"] == 10
    assert outbox["tick_interval"] == 1
    assert outbox["max_tick_interval"] == 30
    assert outbox["retry"] == {
        "max_attempts": 3,
        "base_delay_seconds": 60,
        "max_backoff_seconds": 3600,
        "backoff_multiplier": 2,
        "jitter": True,
        "jitter_factor": 0.25,
    }
    assert outbox["cleanup"]["published_retention_hours"] == 168
    assert outbox["cleanup"]["abandoned_retention_hours"] == 720
    assert outbox["cleanup"]["batch_size"] == 5000


def test_outbox_is_off_without_a_stream_subscription_type(no_env):
    assert Domain(name="Config", config={}).has_outbox is False


def test_telemetry_values(load_toml):
    domain = load_toml("telemetry.toml")

    assert domain.config["telemetry"] == {
        "enabled": True,
        "service_name": "my-service",
        "exporter": "otlp",
        "endpoint": "http://localhost:4317",
        "resource_attributes": {"deployment.environment": "production"},
    }


def test_idempotency_values(load_toml):
    domain = load_toml("idempotency.toml")

    assert domain.config["idempotency"] == {
        "redis_url": "redis://localhost:6379/5",
        "ttl": 86400,
        "error_ttl": 60,
    }


def test_idempotency_is_off_without_redis_url(no_env):
    domain = Domain(name="Config", config={})

    assert domain.config["idempotency"]["redis_url"] is None
    assert domain.idempotency_store.is_active is False


def test_consume_idempotency_values(load_toml):
    domain = load_toml("consume_idempotency.toml")

    assert domain.config["consume_idempotency"] == {
        "cleanup": {"retention_hours": 168, "batch_size": 5000}
    }


def test_logging_values(load_toml):
    domain = load_toml("logging.toml")

    assert domain.config["logging"]["level"] == "INFO"
    assert domain.config["logging"]["format"] == "auto"


def test_lint_values_are_valid(load_toml):
    domain = load_toml("lint.toml")
    lint = domain.config["lint"]

    assert lint == {
        "level": "warn",
        "aggregate_size_limit": 5,
        "handler_breadth_limit": 5,
        "check_infra_imports": False,
        "check_adapter_calls": False,
        "rules": ["my_app.lint.check_names"],
        "suppressions": {"UNHANDLED_EVENT": 3},
    }
    assert validate_lint_table(lint) is None


@pytest.mark.parametrize(
    "bad",
    [
        {"rules": 5},
        {"aggregate_size_limit": "5"},
        {"aggregate_size_limit": "${AGG_LIMIT|8}"},
        {"check_infra_imports": "true"},
    ],
)
def test_lint_bad_values_are_errors(bad):
    assert validate_lint_table(bad) is not None


def test_observatory_retention(load_toml):
    domain = load_toml("observatory.toml")

    assert domain.config["observatory"] == {"trace_retention_days": 7}
    assert domain.trace_emitter._persist is True
    assert domain.trace_emitter._retention_ms == 7 * 86_400_000


def test_partitioning_values(load_toml):
    domain = load_toml("partitioning.toml")

    assert domain.config["server"]["partitioning"] == {
        "lease_ttl_ms": 15000,
        "heartbeat_interval_seconds": 3.0,
        "poll_interval_seconds": 0.25,
        "reap_idle_ms": 3600000,
    }


def test_custom_attributes_become_domain_attributes(load_toml):
    domain = load_toml("custom.toml")

    assert domain.config["custom"]["FOO"] == "bar"
    assert domain.FOO == "bar"


# Multiple environments


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        (None, {"provider": "memory"}),
        ("staging", {"provider": "sqlite", "database_uri": "sqlite:///test.db"}),
        (
            "prod",
            {
                "provider": "postgresql",
                "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
            },
        ),
    ],
)
def test_protean_env_selects_the_overlay(load_toml, monkeypatch, env, expected):
    if env:
        monkeypatch.setenv("PROTEAN_ENV", env)
    domain = load_toml("environments.toml")

    assert domain.config["databases"]["default"] == expected


def test_testing_overlay_base(load_toml):
    domain = load_toml("testing_overlays.toml")
    config = domain.config

    assert config["databases"]["default"] == {
        "provider": "postgresql",
        "database_uri": "postgresql://localhost/myapp_local",
    }
    assert config["brokers"]["default"] == {
        "provider": "redis",
        "URI": "redis://localhost:6379/0",
    }
    assert config["event_processing"] == "async"


def test_testing_overlay_test(load_toml, monkeypatch):
    monkeypatch.setenv("PROTEAN_ENV", "test")
    config = load_toml("testing_overlays.toml").config

    assert config["testing"] is True
    assert config["event_processing"] == "sync"
    # Only the URI changes; the provider comes from the base section
    assert config["databases"]["default"] == {
        "provider": "postgresql",
        "database_uri": "postgresql://localhost/myapp_test",
    }
    assert config["brokers"]["default"]["provider"] == "redis"


def test_testing_overlay_memory(load_toml, monkeypatch):
    monkeypatch.setenv("PROTEAN_ENV", "memory")
    config = load_toml("testing_overlays.toml").config

    assert config["testing"] is True
    assert config["event_processing"] == "sync"
    assert config["databases"]["default"]["provider"] == "memory"
    assert config["event_store"] == {"provider": "memory"}
    assert config["brokers"]["default"]["provider"] == "inline"
