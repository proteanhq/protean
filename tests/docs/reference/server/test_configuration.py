"""The examples on ``docs/reference/server/configuration.md`` behave as the page says."""

import ast
import logging
from enum import Enum

import pytest

from protean import Domain
from protean.exceptions import ConfigurationError
from protean.server import Engine
from protean.server.subscription.config_resolver import ConfigResolver
from protean.server.subscription.profiles import (
    PROFILE_DEFAULTS,
    SubscriptionProfile,
)
from tests.docs.support import DOCS_SRC, load_example
from tests.support.snippets import read_include

pytestmark = pytest.mark.no_test_domain

EXAMPLES = DOCS_SRC / "reference/server/configuration"


def shown_dict(spec: str) -> dict:
    """Return the dict literal the page shows for the section ``spec``."""
    return ast.literal_eval(
        read_include(f"reference/server/configuration/{spec}", [DOCS_SRC])
    )


def plain(config: dict) -> dict:
    """Turn enum values into their strings, as the page writes them."""
    return {
        key: value.value if isinstance(value, Enum) else value
        for key, value in config.items()
    }


def toml_domain(tmp_path, *names: str) -> Domain:
    """Build a domain from the page's TOML files, joined into one domain.toml."""
    text = "\n".join((EXAMPLES / name).read_text() for name in names)
    (tmp_path / "domain.toml").write_text(text)
    return Domain(root_path=str(tmp_path), name="Shop")


def resolve(domain: Domain, handler) -> dict:
    return plain(ConfigResolver(domain).resolve(handler).to_dict())


def bare_handler(name: str) -> type:
    """A handler class with no Meta options, so only the TOML configures it."""
    return type(name, (), {})


@pytest.mark.parametrize("name", ["production", "fast", "batch", "debug"])
def test_stream_profile_dicts_match_the_profile_defaults(name):
    load_example("reference/server/configuration/001.py")
    defaults = plain(PROFILE_DEFAULTS[SubscriptionProfile(name)])
    # The page leaves out origin_stream, which is None in every profile
    assert defaults.pop("origin_stream") is None

    assert shown_dict(f"001.py:{name}") == defaults


def test_projection_profile_dict_matches_the_profile_defaults():
    shown = shown_dict("001.py:projection")
    defaults = plain(PROFILE_DEFAULTS[SubscriptionProfile.PROJECTION])

    assert shown == {key: defaults[key] for key in shown}
    assert shown["subscription_type"] == "event_store"
    assert shown["enable_dlq"] is False
    assert shown["retention_maxlen"] is None


def test_custom_profile_inherits_fast_and_overrides_one_field(tmp_path):
    domain = toml_domain(tmp_path, "custom_profile.toml")

    assert domain.config["server"]["profiles"]["myfast"] == {
        "inherits": "fast",
        "messages_per_tick": 25,
    }


def test_a_handler_named_in_the_toml_uses_the_custom_profile(tmp_path):
    domain = toml_domain(tmp_path, "custom_profile_handler.toml")
    assert domain.config["server"]["subscriptions"]["NotificationHandler"] == {
        "profile": "myfast"
    }

    domain = toml_domain(tmp_path, "custom_profile.toml", "custom_profile_handler.toml")
    resolved = resolve(domain, bare_handler("NotificationHandler"))

    assert resolved["messages_per_tick"] == 25
    # Every other field comes from the inherited `fast` profile
    assert resolved["blocking_timeout_ms"] == 100
    assert resolved["max_retries"] == 2
    assert resolved["retry_delay_seconds"] == 0


def test_a_custom_profile_cannot_reuse_a_built_in_name(tmp_path):
    (tmp_path / "domain.toml").write_text(
        "[server.profiles.fast]\nmessages_per_tick = 25\n"
    )
    domain = Domain(root_path=str(tmp_path), name="Shop")

    with pytest.raises(ConfigurationError, match="fast"):
        resolve(domain, bare_handler("NotificationHandler"))


def test_decorator_options_combine_profile_and_config():
    example = load_example("reference/server/configuration/002.py")
    example.domain.init(traverse=False)

    resolved = resolve(example.domain, example.OrderEventHandler)

    assert resolved["subscription_type"] == "stream"
    # subscription_config wins over the profile
    assert resolved["messages_per_tick"] == 50
    assert resolved["enable_dlq"] is True
    # The rest comes from the `production` profile
    assert resolved["blocking_timeout_ms"] == 5000
    assert resolved["retention_maxlen"] == 100_000


def test_server_toml_sets_the_defaults_and_handler_overrides(tmp_path):
    domain = toml_domain(tmp_path, "server.toml")
    server = domain.config["server"]

    assert server["default_subscription_type"] == "stream"
    assert server["default_subscription_profile"] == "production"
    assert server["messages_per_tick"] == 100
    assert server["stream_subscription"]["circuit_breaker_threshold"] == 10
    assert server["event_store_subscription"]["gap_timeout_seconds"] == 5
    assert server["broker_subscription"]["enable_dlq"] is True
    assert server["version_retry"]["max_delay_seconds"] == 1.0

    order_handler = resolve(domain, bare_handler("OrderEventHandler"))
    assert order_handler["subscription_type"] == "stream"
    assert order_handler["messages_per_tick"] == 50
    # From the handler's `fast` profile
    assert order_handler["blocking_timeout_ms"] == 100
    assert order_handler["max_retries"] == 2

    projector = resolve(domain, bare_handler("InventoryProjector"))
    assert projector["subscription_type"] == "event_store"
    assert projector["enable_dlq"] is False

    # A handler the TOML does not name gets the server-level defaults
    other = resolve(domain, bare_handler("OtherHandler"))
    assert other["subscription_type"] == "stream"
    assert other["messages_per_tick"] == 100
    assert other["blocking_timeout_ms"] == 5000


@pytest.mark.parametrize(
    "environment, profile, messages_per_tick, max_retries",
    [
        (None, "debug", 100, 3),
        ("prod", "production", 200, 5),
        ("staging", "fast", 100, 3),
    ],
)
def test_environment_sections_override_the_server_settings(
    tmp_path, monkeypatch, environment, profile, messages_per_tick, max_retries
):
    if environment is None:
        monkeypatch.delenv("PROTEAN_ENV", raising=False)
    else:
        monkeypatch.setenv("PROTEAN_ENV", environment)

    server = toml_domain(tmp_path, "environments.toml").config["server"]

    assert server["default_subscription_profile"] == profile
    assert server["messages_per_tick"] == messages_per_tick
    assert server["stream_subscription"]["max_retries"] == max_retries


@pytest.mark.parametrize(
    "handler, section",
    [
        ("OrderEventHandler", "production_resolved"),
        ("NotificationEventHandler", "fast_resolved"),
        ("OrderSummaryProjector", "projector_resolved"),
    ],
)
def test_examples_resolve_to_the_config_the_page_shows(handler, section):
    example = load_example("reference/server/configuration/003.py")
    example.domain.init(traverse=False)

    resolved = resolve(example.domain, getattr(example, handler))
    shown = shown_dict(f"003.py:{section}")

    assert {key: resolved[key] for key in shown} == shown


def test_origin_stream_filter_reaches_the_subscription():
    example = load_example("reference/server/configuration/003.py")
    example.domain.init(traverse=False)

    resolved = resolve(example.domain, example.UserActionNotificationHandler)

    assert resolved["subscription_type"] == "event_store"
    assert resolved["origin_stream"] == "user_actions"
    assert example.UserActionNotificationHandler.meta_.stream_category == "order"


def test_mixed_example_resolves_to_the_config_the_page_shows(tmp_path):
    example = load_example("reference/server/configuration/004.py")
    example.domain.init(traverse=False)
    domain = toml_domain(tmp_path, "mixed.toml")

    resolved = resolve(domain, example.SpecialHandler)
    shown = shown_dict("004.py:special_resolved")

    assert {key: resolved[key] for key in shown} == shown


def test_debug_profile_named_on_a_handler_applies_in_full(tmp_path):
    domain = toml_domain(tmp_path, "development.toml")
    resolved = resolve(domain, bare_handler("OrderEventHandler"))

    debug = plain(PROFILE_DEFAULTS[SubscriptionProfile.DEBUG])
    assert {key: resolved[key] for key in debug} == debug


def test_debug_as_default_subscription_profile_changes_nothing():
    handler = bare_handler("OrderEventHandler")
    with_debug = Domain(
        name="Shop", config={"server": {"default_subscription_profile": "debug"}}
    )
    without = Domain(name="Shop")

    # The built-in server-level defaults set the fields `debug` sets
    assert resolve(with_debug, handler) == resolve(without, handler)


def test_debug_as_default_profile_caps_stream_retention_on_stream_type():
    handler = bare_handler("OrderEventHandler")
    stream = {"default_subscription_type": "stream"}
    with_debug = resolve(
        Domain(
            name="Shop",
            config={"server": {**stream, "default_subscription_profile": "debug"}},
        ),
        handler,
    )
    without = resolve(Domain(name="Shop", config={"server": stream}), handler)

    differing = {
        k: (with_debug[k], without[k])
        for k in with_debug
        if with_debug[k] != without[k]
    }
    assert differing == {"retention_maxlen": (1_000, None)}


def test_outbox_with_event_store_subscriptions_is_a_conflict():
    domain = Domain(name="Shop", config={"enable_outbox": True})

    with pytest.raises(
        ConfigurationError,
        match="Configuration conflict: 'enable_outbox' is True but "
        "'server.default_subscription_type' is 'event_store'",
    ):
        domain.init(traverse=False)


def test_stream_subscription_type_enables_the_outbox():
    domain = Domain(
        name="Shop", config={"server": {"default_subscription_type": "stream"}}
    )

    assert domain.has_outbox is True


def test_unknown_external_broker_fails_engine_startup(tmp_path):
    (tmp_path / "domain.toml").write_text(
        '[server]\ndefault_subscription_type = "stream"\n\n'
        '[outbox]\nexternal_brokers = ["nonexistent_broker"]\n'
    )
    domain = Domain(root_path=str(tmp_path), name="Shop")
    domain.init(traverse=False)

    with pytest.raises(
        ValueError,
        match="External broker 'nonexistent_broker' configured in "
        "outbox.external_brokers but not found in domain broker configuration",
    ):
        Engine(domain, test_mode=True)


def test_published_events_without_external_brokers_log_a_warning(caplog):
    example = load_example("reference/server/configuration/002.py")
    example.domain.register(
        type("OrderPaid", (example.OrderCreated,), {}),
        part_of=example.Order,
        published=True,
    )

    with caplog.at_level(logging.WARNING):
        example.domain.init(traverse=False)

    assert (
        "Domain has published events but no external_brokers configured "
        "in outbox settings. Published events will only be dispatched internally."
    ) in caplog.text


def test_unknown_profile_fails_when_the_engine_builds_subscriptions():
    example = load_example("reference/server/configuration/002.py")
    example.OrderEventHandler.meta_.subscription_profile = "nonexistent"
    example.domain.init(traverse=False)

    with pytest.raises(
        ConfigurationError,
        match="Unknown subscription profile 'nonexistent'. "
        "Valid profiles: batch, debug, fast, production, projection",
    ):
        Engine(example.domain, test_mode=True)


def test_unknown_subscription_type_falls_back_to_event_store_with_a_warning(caplog):
    example = load_example("reference/server/configuration/002.py")
    example.OrderEventHandler.meta_.subscription_type = "invalid"
    example.domain.init(traverse=False)

    with caplog.at_level(logging.WARNING):
        config = ConfigResolver(example.domain).resolve(example.OrderEventHandler)

    assert config.subscription_type.value == "event_store"
    assert "Unknown subscription type 'invalid', defaulting to EVENT_STORE" in (
        caplog.text
    )


def test_enable_dlq_is_turned_off_for_an_event_store_subscription():
    example = load_example("reference/server/configuration/002.py")
    example.OrderEventHandler.meta_.subscription_type = "event_store"
    example.OrderEventHandler.meta_.subscription_config = {
        "enable_dlq": True,
        "messages_per_tick": 25,
    }
    example.domain.init(traverse=False)

    config = ConfigResolver(example.domain).resolve(example.OrderEventHandler)

    assert config.subscription_type.value == "event_store"
    assert config.enable_dlq is False
    assert config.messages_per_tick == 25
