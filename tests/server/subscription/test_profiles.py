"""Tests for subscription configuration profiles system.

This module contains comprehensive tests for the SubscriptionConfig,
SubscriptionType, SubscriptionProfile enums, and profile loading functionality.
"""

import dataclasses

import pytest

from protean.exceptions import ConfigurationError
from protean.server.subscription.profiles import (
    DEFAULT_CONFIG,
    PROFILE_DEFAULTS,
    SubscriptionConfig,
    SubscriptionProfile,
    SubscriptionType,
    build_profile_registry,
)


class TestSubscriptionTypeEnum:
    """Tests for SubscriptionType enum."""

    def test_subscription_type_members(self):
        """SubscriptionType has exactly STREAM and EVENT_STORE, built from their values."""
        assert {t.value: t for t in SubscriptionType} == {
            "stream": SubscriptionType.STREAM,
            "event_store": SubscriptionType.EVENT_STORE,
        }
        assert SubscriptionType("stream") == SubscriptionType.STREAM
        assert SubscriptionType("event_store") == SubscriptionType.EVENT_STORE


class TestSubscriptionProfileEnum:
    """Tests for SubscriptionProfile enum."""

    def test_subscription_profile_members(self):
        """SubscriptionProfile has exactly five members, built from their values."""
        expected = {
            "production": SubscriptionProfile.PRODUCTION,
            "fast": SubscriptionProfile.FAST,
            "batch": SubscriptionProfile.BATCH,
            "debug": SubscriptionProfile.DEBUG,
            "projection": SubscriptionProfile.PROJECTION,
        }
        assert {p.value: p for p in SubscriptionProfile} == expected
        for value, member in expected.items():
            assert SubscriptionProfile(value) == member


PROFILE_EXPECTATIONS = [
    (
        SubscriptionProfile.PRODUCTION,
        {
            "subscription_type": SubscriptionType.STREAM,
            "messages_per_tick": 100,
            "blocking_timeout_ms": 5000,
            "max_retries": 3,
            "enable_dlq": True,
            "retention_maxlen": 100_000,
        },
    ),
    (
        SubscriptionProfile.FAST,
        {
            "subscription_type": SubscriptionType.STREAM,
            "messages_per_tick": 10,
            "blocking_timeout_ms": 100,
            "retry_delay_seconds": 0,
            "retention_maxlen": 100_000,
        },
    ),
    (
        SubscriptionProfile.BATCH,
        {
            "subscription_type": SubscriptionType.STREAM,
            "messages_per_tick": 500,
            "blocking_timeout_ms": 10000,
            "max_retries": 5,
            "retention_maxlen": 500_000,
        },
    ),
    (
        SubscriptionProfile.DEBUG,
        {
            "subscription_type": SubscriptionType.STREAM,
            "messages_per_tick": 1,
            "tick_interval": 1,
            "enable_dlq": False,
            "retention_maxlen": 1_000,
        },
    ),
    (
        SubscriptionProfile.PROJECTION,
        {
            "subscription_type": SubscriptionType.EVENT_STORE,
            "enable_dlq": False,
            "retention_maxlen": None,
        },
    ),
]


class TestProfileDefaults:
    """Tests for PROFILE_DEFAULTS dictionary."""

    def test_all_profiles_have_defaults(self):
        """All profiles should have entries in PROFILE_DEFAULTS."""
        for profile in SubscriptionProfile:
            assert profile in PROFILE_DEFAULTS

    @pytest.mark.parametrize("profile, expected", PROFILE_EXPECTATIONS)
    def test_profile_defaults(self, profile, expected):
        """Each profile's PROFILE_DEFAULTS entry holds its documented values."""
        defaults = PROFILE_DEFAULTS[profile]
        for key, value in expected.items():
            assert defaults[key] == value


class TestSubscriptionConfigCreation:
    """Tests for SubscriptionConfig creation."""

    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            (
                {},
                {
                    "subscription_type": SubscriptionType.STREAM,
                    "messages_per_tick": DEFAULT_CONFIG["messages_per_tick"],
                    "tick_interval": DEFAULT_CONFIG["tick_interval"],
                    "retention_maxlen": None,
                },
            ),
            (
                {
                    "subscription_type": SubscriptionType.STREAM,
                    "messages_per_tick": 50,
                    "blocking_timeout_ms": 2000,
                    "enable_dlq": False,
                },
                None,
            ),
            (
                {
                    "subscription_type": SubscriptionType.EVENT_STORE,
                    "enable_dlq": False,
                },
                None,
            ),
            ({"tick_interval": 0}, None),
            ({"blocking_timeout_ms": 1}, None),
            ({"max_retries": 0}, None),
            ({"retention_maxlen": 1}, None),
        ],
        ids=[
            "defaults",
            "explicit_values",
            "event_store_without_dlq",
            "zero_tick_interval",
            "smallest_blocking_timeout",
            "zero_max_retries",
            "smallest_retention",
        ],
    )
    def test_config_creation(self, kwargs, expected):
        """SubscriptionConfig accepts defaults, explicit values and boundary values.

        With no expected table the config must hold exactly the values passed.
        """
        config = SubscriptionConfig(**kwargs)
        for key, value in (expected or kwargs).items():
            assert getattr(config, key) == value


class TestSubscriptionConfigFromProfile:
    """Tests for SubscriptionConfig.from_profile() method."""

    @pytest.mark.parametrize("profile, expected", PROFILE_EXPECTATIONS)
    def test_from_profile_loads_defaults(self, profile, expected):
        """Creating config from a profile loads that profile's values."""
        config = SubscriptionConfig.from_profile(profile)
        for key, value in expected.items():
            assert getattr(config, key) == value

    @pytest.mark.parametrize(
        "overrides",
        [
            {"messages_per_tick": 50},
            {"messages_per_tick": 25, "max_retries": 5, "enable_dlq": False},
        ],
        ids=["single", "multiple"],
    )
    def test_profile_with_overrides(self, overrides):
        """Overrides replace their fields; every other field keeps the profile value."""
        config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PRODUCTION, **overrides
        )
        production = PROFILE_DEFAULTS[SubscriptionProfile.PRODUCTION]
        for key in ("messages_per_tick", "blocking_timeout_ms", "max_retries"):
            assert getattr(config, key) == overrides.get(key, production[key])
        assert config.enable_dlq is overrides.get("enable_dlq", True)

    def test_profile_override_subscription_type(self):
        """Profile subscription_type can be overridden."""
        config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PRODUCTION,
            subscription_type=SubscriptionType.EVENT_STORE,
            enable_dlq=False,  # Must disable DLQ for EVENT_STORE
        )
        assert config.subscription_type == SubscriptionType.EVENT_STORE
        # from_profile clears the inherited stream retention for EVENT_STORE.
        assert config.retention_maxlen is None

    def test_profile_override_subscription_type_rejects_explicit_retention(self):
        """An explicit retention_maxlen alongside an EVENT_STORE override is rejected.

        Unlike the inherited-from-profile case (cleared silently, see
        test_profile_override_subscription_type), a retention_maxlen passed
        directly to from_profile() is a config mistake and must surface via
        validate() rather than being dropped.
        """
        with pytest.raises(ConfigurationError) as exc:
            SubscriptionConfig.from_profile(
                SubscriptionProfile.PRODUCTION,
                subscription_type=SubscriptionType.EVENT_STORE,
                enable_dlq=False,
                retention_maxlen=1_000,
            )
        assert "retention_maxlen is not supported for EVENT_STORE" in str(exc.value)


class TestSubscriptionConfigFromDict:
    """Tests for SubscriptionConfig.from_dict() method."""

    def test_from_empty_dict(self):
        """Creating config from empty dict uses default values."""
        config = SubscriptionConfig.from_dict({})
        assert config.subscription_type == DEFAULT_CONFIG["subscription_type"]
        assert config.messages_per_tick == DEFAULT_CONFIG["messages_per_tick"]

    @pytest.mark.parametrize("name", ["production", "PRODUCTION", "Production"])
    def test_from_dict_with_profile_name_in_any_case(self, name):
        """A profile name in any case loads that profile's defaults."""
        config = SubscriptionConfig.from_dict({"profile": name})
        assert config.messages_per_tick == 100
        assert config.blocking_timeout_ms == 5000

    def test_from_dict_with_profile_and_overrides(self):
        """Keys in the dict override the profile; missing keys keep profile values."""
        config = SubscriptionConfig.from_dict(
            {
                "profile": "production",
                "messages_per_tick": 50,
                "max_retries": 10,
            }
        )
        assert config.messages_per_tick == 50
        assert config.max_retries == 10
        prod_defaults = PROFILE_DEFAULTS[SubscriptionProfile.PRODUCTION]
        assert config.blocking_timeout_ms == prod_defaults["blocking_timeout_ms"]
        assert config.enable_dlq == prod_defaults["enable_dlq"]

    @pytest.mark.parametrize(
        "value, extra, expected",
        [
            ("stream", {"messages_per_tick": 20}, SubscriptionType.STREAM),
            ("STREAM", {}, SubscriptionType.STREAM),
            (
                SubscriptionType.EVENT_STORE,
                {"enable_dlq": False},
                SubscriptionType.EVENT_STORE,
            ),
        ],
        ids=["string", "upper_case_string", "enum"],
    )
    def test_from_dict_with_subscription_type(self, value, extra, expected):
        """subscription_type may be a string in any case or the enum."""
        config = SubscriptionConfig.from_dict({"subscription_type": value, **extra})
        assert config.subscription_type == expected
        for key, extra_value in extra.items():
            assert getattr(config, key) == extra_value

    def test_from_dict_with_all_options(self):
        """Creating config from dict with all options specified."""
        config = SubscriptionConfig.from_dict(
            {
                "subscription_type": "stream",
                "messages_per_tick": 75,
                "tick_interval": 2,
                "blocking_timeout_ms": 3000,
                "max_retries": 4,
                "retry_delay_seconds": 2,
                "enable_dlq": True,
                "position_update_interval": 20,
                "origin_stream": "test-stream",
            }
        )
        assert config.subscription_type == SubscriptionType.STREAM
        assert config.messages_per_tick == 75
        assert config.tick_interval == 2
        assert config.blocking_timeout_ms == 3000
        assert config.max_retries == 4
        assert config.retry_delay_seconds == 2
        assert config.enable_dlq is True
        assert config.position_update_interval == 20
        assert config.origin_stream == "test-stream"

    def test_from_dict_type_coercion(self):
        """Float counts become ints and truthy values become bools."""
        config = SubscriptionConfig.from_dict({"messages_per_tick": 50.0})
        assert config.messages_per_tick == 50
        assert isinstance(config.messages_per_tick, int)

        assert SubscriptionConfig.from_dict({"enable_dlq": 1}).enable_dlq is True
        assert SubscriptionConfig.from_dict({"enable_dlq": 0}).enable_dlq is False

    def test_from_dict_does_not_modify_original(self):
        """from_dict should not modify the original dictionary."""
        original = {"profile": "production", "messages_per_tick": 50}
        original_copy = dict(original)
        SubscriptionConfig.from_dict(original)
        assert original == original_copy

    def test_from_dict_ignores_unknown_keys(self):
        """Keys that are not SubscriptionConfig fields are ignored."""
        config = SubscriptionConfig.from_dict(
            {"messages_per_tick": 7, "not_a_field": "x"}
        )
        assert config.messages_per_tick == 7
        assert not hasattr(config, "not_a_field")


class TestSubscriptionConfigValidation:
    """Tests for SubscriptionConfig validation rules."""

    @pytest.mark.parametrize(
        "kwargs, message",
        [
            (
                {"subscription_type": SubscriptionType.EVENT_STORE, "enable_dlq": True},
                "enable_dlq is not supported for EVENT_STORE",
            ),
            (
                {
                    "subscription_type": SubscriptionType.EVENT_STORE,
                    "enable_dlq": False,
                    "retention_maxlen": 1_000,
                },
                "retention_maxlen is not supported for EVENT_STORE",
            ),
            ({"retention_maxlen": 0}, "retention_maxlen must be positive when set"),
            ({"retention_maxlen": -5}, "retention_maxlen must be positive when set"),
            ({"messages_per_tick": -1}, "messages_per_tick must be positive"),
            ({"messages_per_tick": 0}, "messages_per_tick must be positive"),
            ({"tick_interval": -1}, "tick_interval must be non-negative"),
            ({"blocking_timeout_ms": 0}, "blocking_timeout_ms must be positive"),
            ({"blocking_timeout_ms": -1}, "blocking_timeout_ms must be positive"),
            ({"max_retries": -1}, "max_retries must be non-negative"),
            ({"retry_delay_seconds": -1}, "retry_delay_seconds must be non-negative"),
            (
                {
                    "subscription_type": SubscriptionType.EVENT_STORE,
                    "enable_dlq": False,
                    "position_update_interval": -1,
                },
                "position_update_interval must be positive",
            ),
            (
                {
                    "subscription_type": SubscriptionType.EVENT_STORE,
                    "enable_dlq": False,
                    "position_update_interval": 0,
                },
                "position_update_interval must be positive",
            ),
        ],
        ids=[
            "event_store_with_dlq",
            "event_store_with_retention",
            "zero_retention",
            "negative_retention",
            "negative_messages_per_tick",
            "zero_messages_per_tick",
            "negative_tick_interval",
            "zero_blocking_timeout",
            "negative_blocking_timeout",
            "negative_max_retries",
            "negative_retry_delay",
            "negative_position_update_interval",
            "zero_position_update_interval",
        ],
    )
    def test_invalid_value_raises_error(self, kwargs, message):
        """Each out-of-range value is rejected with a message naming the field."""
        with pytest.raises(ConfigurationError) as exc_info:
            SubscriptionConfig(**kwargs)
        assert message in str(exc_info.value)

    @pytest.mark.parametrize(
        "config, message",
        [
            ({"profile": "unknown"}, "Unknown subscription profile"),
            ({"subscription_type": "unknown"}, "Unknown subscription type"),
        ],
        ids=["profile", "subscription_type"],
    )
    def test_unknown_name_in_dict_raises_error(self, config, message):
        """An unknown profile or subscription type name is rejected."""
        with pytest.raises(ConfigurationError) as exc_info:
            SubscriptionConfig.from_dict(config)
        assert message in str(exc_info.value)

    @pytest.mark.parametrize(
        "resolver, message",
        [
            (
                SubscriptionConfig._resolve_profile,
                "Profile must be a string or SubscriptionProfile",
            ),
            (
                SubscriptionConfig._resolve_subscription_type,
                "Subscription type must be a string or SubscriptionType",
            ),
        ],
        ids=["profile", "subscription_type"],
    )
    def test_value_of_wrong_type_raises_error(self, resolver, message):
        """A value that is neither a string nor the enum is rejected."""
        with pytest.raises(ConfigurationError) as exc_info:
            resolver(123)
        assert message in str(exc_info.value)

    def test_from_profile_with_invalid_profile_not_in_defaults(self):
        """from_profile raises ConfigurationError for a value not in PROFILE_DEFAULTS."""
        with pytest.raises(ConfigurationError, match="Unknown subscription profile"):
            SubscriptionConfig.from_profile("nonexistent")  # type: ignore[arg-type]

    def test_resolve_profile_returns_each_enum_variant(self):
        """_resolve_profile should return the same enum for all SubscriptionProfile variants."""
        for profile in SubscriptionProfile:
            result = SubscriptionConfig._resolve_profile(profile)
            assert result is profile


class TestSubscriptionConfigToDict:
    """Tests for SubscriptionConfig.to_dict() method."""

    def test_to_dict_returns_all_fields(self):
        """to_dict returns every configuration field, with subscription_type as a string."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)
        result = config.to_dict()

        assert set(result) == {f.name for f in dataclasses.fields(SubscriptionConfig)}
        assert result["subscription_type"] == "stream"

    def test_to_dict_roundtrip(self):
        """Config can be recreated from to_dict output."""
        original = SubscriptionConfig.from_profile(
            SubscriptionProfile.PRODUCTION,
            messages_per_tick=50,
            origin_stream="test-stream",
        )
        dict_repr = original.to_dict()
        recreated = SubscriptionConfig.from_dict(dict_repr)

        assert recreated.subscription_type == original.subscription_type
        assert recreated.messages_per_tick == original.messages_per_tick
        assert recreated.origin_stream == original.origin_stream


ENVIRONMENT_VARIABLES = ["PROTEAN_ENV", "PYTHON_ENV", "ENV", "ENVIRONMENT"]


@pytest.fixture
def clean_environment(monkeypatch):
    """Remove every environment variable that production detection reads."""
    for name in ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


class TestProductionEnvironmentDetection:
    """Tests for production environment detection."""

    @pytest.mark.parametrize(
        "name, value",
        [
            ("PROTEAN_ENV", "production"),
            ("PROTEAN_ENV", "prod"),
            ("PROTEAN_ENV", "PRODUCTION"),
            ("PROTEAN_ENV", "Production"),
            ("PYTHON_ENV", "production"),
            ("ENV", "production"),
            ("ENVIRONMENT", "production"),
        ],
    )
    def test_detects_production(self, clean_environment, name, value):
        """Any of the variables set to production, in any case, means production."""
        clean_environment.setenv(name, value)
        assert SubscriptionConfig._is_production_environment() is True

    @pytest.mark.parametrize("value", ["development", "staging", None])
    def test_non_production_env(self, clean_environment, value):
        """Other values, or no variables at all, do not mean production."""
        if value is not None:
            clean_environment.setenv("PROTEAN_ENV", value)
        assert SubscriptionConfig._is_production_environment() is False


class TestEventStoreWarning:
    """Tests for EVENT_STORE usage warnings."""

    @pytest.mark.parametrize(
        "env, kwargs, warns",
        [
            (
                "production",
                {
                    "subscription_type": SubscriptionType.EVENT_STORE,
                    "enable_dlq": False,
                },
                True,
            ),
            (
                "development",
                {
                    "subscription_type": SubscriptionType.EVENT_STORE,
                    "enable_dlq": False,
                },
                False,
            ),
            ("production", {"subscription_type": SubscriptionType.STREAM}, False),
        ],
        ids=["event_store_in_production", "event_store_in_development", "stream"],
    )
    def test_event_store_warning(self, clean_environment, caplog, env, kwargs, warns):
        """Only an EVENT_STORE config in production logs the warning."""
        clean_environment.setenv("PROTEAN_ENV", env)
        SubscriptionConfig(**kwargs)

        warned = "EventStoreSubscription is being used in production" in caplog.text
        assert warned is warns


class TestBuildProfileRegistry:
    """Tests for build_profile_registry, the merged built-in + custom registry."""

    def test_custom_profile_inherits_builtin_and_overrides(self):
        """inherits = 'fast' + messages_per_tick=25 keeps fast defaults, overrides one."""
        registry = build_profile_registry(
            {"myfast": {"inherits": "fast", "messages_per_tick": 25}}
        )

        fast = PROFILE_DEFAULTS[SubscriptionProfile.FAST]
        assert registry["myfast"]["messages_per_tick"] == 25
        # The rest of fast's defaults carry through unchanged.
        assert registry["myfast"]["blocking_timeout_ms"] == fast["blocking_timeout_ms"]
        assert registry["myfast"]["max_retries"] == fast["max_retries"]
        assert registry["myfast"]["retry_delay_seconds"] == fast["retry_delay_seconds"]
        assert registry["myfast"]["subscription_type"] == fast["subscription_type"]

    def test_custom_profile_without_inherits_bases_on_default_config(self):
        """No inherits bases on DEFAULT_CONFIG and applies the overrides."""
        registry = build_profile_registry({"custom": {"max_retries": 9}})

        assert registry["custom"]["max_retries"] == 9
        # Every other field comes from DEFAULT_CONFIG.
        assert (
            registry["custom"]["messages_per_tick"]
            == DEFAULT_CONFIG["messages_per_tick"]
        )
        assert (
            registry["custom"]["blocking_timeout_ms"]
            == DEFAULT_CONFIG["blocking_timeout_ms"]
        )

    def test_custom_profile_name_is_case_normalized(self):
        """A mixed-case section name is registered lowercased."""
        registry = build_profile_registry({"MyFast": {"inherits": "fast"}})

        assert "myfast" in registry
        assert "MyFast" not in registry

    @pytest.mark.parametrize(
        "custom_profiles, named",
        [
            ({"production": {"messages_per_tick": 1}}, "production"),
            ({"Production": {"messages_per_tick": 1}}, "Production"),
            ({"loopy": {"inherits": "loopy"}}, "loopy"),
            ({"base": {"max_retries": 1}, "child": {"inherits": "base"}}, "base"),
            ({"orphan": {"inherits": "nonexistent"}}, "nonexistent"),
            ({"weird": "not-a-dict"}, "weird"),
            ({"bad": {"not_a_field": 1}}, "not_a_field"),
            ({"d": {"dlq_retention_hours": 1}}, "dlq_retention_hours"),
            ({"d": {"dlq_alert_threshold": 1}}, "dlq_alert_threshold"),
            ({"arr": {"inherits": ["fast"]}}, "arr"),
            ({"tbl": {"inherits": {"name": "fast"}}}, "tbl"),
            ({"weird": {123: "batch"}}, "weird"),
            ({123: {"messages_per_tick": 1}}, "123"),
        ],
        ids=[
            "shadows_builtin",
            "shadows_builtin_in_other_case",
            "inherits_itself",
            "inherits_custom_profile",
            "inherits_unknown_profile",
            "section_not_a_table",
            "unknown_field",
            "dlq_retention_hours_not_a_profile_field",
            "dlq_alert_threshold_not_a_profile_field",
            "inherits_array",
            "inherits_table",
            "non_string_override_key",
            "non_string_profile_name",
        ],
    )
    def test_invalid_custom_profile_raises(self, custom_profiles, named):
        """An invalid custom profile raises ConfigurationError naming the culprit.

        The dlq fields are real SubscriptionConfig fields left out of the
        profile allow-list. The non-string inherits, override key and profile
        name cases must raise ConfigurationError, not a raw TypeError from
        hashing or sorting the value.
        """
        with pytest.raises(ConfigurationError) as exc:
            build_profile_registry(custom_profiles)

        assert named in str(exc.value)

    def test_building_custom_registry_does_not_mutate_builtin_defaults(self):
        """Overriding fields in a custom profile leaves PROFILE_DEFAULTS pristine."""
        before = {
            profile: dict(defaults) for profile, defaults in PROFILE_DEFAULTS.items()
        }

        registry = build_profile_registry(
            {"myfast": {"inherits": "fast", "messages_per_tick": 999}}
        )
        # Mutating a returned entry must not leak into the shared defaults either.
        registry["fast"]["messages_per_tick"] = -1
        registry["myfast"]["max_retries"] = -1

        for profile, defaults in PROFILE_DEFAULTS.items():
            assert defaults == before[profile]

    def test_custom_profile_subscription_type_stays_string(self):
        """A subscription_type override is left as its raw string for later resolution."""
        registry = build_profile_registry(
            {"es": {"inherits": "projection", "subscription_type": "event_store"}}
        )

        assert registry["es"]["subscription_type"] == "event_store"

    def test_none_override_keeps_inherited_value(self):
        """A None override under `inherits` keeps the inherited value, not the default.

        `messages_per_tick = None` over an inherited batch (500) must stay 500,
        not silently revert to DEFAULT_CONFIG's 10 once the downstream merge drops
        the None.
        """
        registry = build_profile_registry(
            {"keepy": {"inherits": "batch", "messages_per_tick": None}}
        )

        batch = PROFILE_DEFAULTS[SubscriptionProfile.BATCH]
        assert registry["keepy"]["messages_per_tick"] == batch["messages_per_tick"]
        assert (
            registry["keepy"]["messages_per_tick"]
            != DEFAULT_CONFIG["messages_per_tick"]
        )


class TestRetentionMaxlen:
    """Tests for the retention_maxlen stream-retention config field."""

    def test_retention_is_off_by_default(self):
        """retention_maxlen defaults to None (trimming off)."""
        assert DEFAULT_CONFIG["retention_maxlen"] is None
        assert SubscriptionConfig().retention_maxlen is None

    def test_from_profile_override_retention(self):
        """An explicit retention_maxlen override wins over the profile default."""
        config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PRODUCTION,
            retention_maxlen=42,
        )
        assert config.retention_maxlen == 42

    def test_from_dict_reads_retention(self):
        """from_dict picks up retention_maxlen and coerces it to int."""
        config = SubscriptionConfig.from_dict({"retention_maxlen": 50})
        assert config.retention_maxlen == 50

    def test_to_dict_round_trips_retention(self):
        """to_dict includes retention_maxlen for a full round-trip."""
        config = SubscriptionConfig(retention_maxlen=123)
        assert config.to_dict()["retention_maxlen"] == 123

    def test_retention_is_a_profile_field(self):
        """retention_maxlen is settable on a custom [server.profiles] profile."""
        registry = build_profile_registry(
            {"capped": {"inherits": "production", "retention_maxlen": 42}}
        )
        assert registry["capped"]["retention_maxlen"] == 42


class TestTheProfilesSlotMustBeATable:
    """A falsy scalar used to be accepted in silence.

    The type check sat behind `if not custom_profiles: return`, so
    `profiles = false`, `0` and `""` returned the built-in registry without
    complaint while `profiles = "x"` raised. That asymmetry is the wrong way
    round, and it is the same shape as the `priority_lanes` guard fixed
    alongside it: the mis-typed value nobody hears about is the dangerous one.
    """

    @pytest.mark.parametrize("scalar", [False, 0, "", "x", 3.5, []])
    def test_a_scalar_is_rejected_whether_truthy_or_not(self, scalar):
        with pytest.raises(ConfigurationError, match=r"\[server.profiles\] must be"):
            build_profile_registry(scalar)

    @pytest.mark.parametrize("empty", [None, {}])
    def test_nothing_configured_yields_the_built_ins(self, empty):
        registry = build_profile_registry(empty)

        assert registry
        assert set(registry) == {p.value for p in SubscriptionProfile}
        for profile in SubscriptionProfile:
            assert registry[profile.value] == PROFILE_DEFAULTS[profile]
