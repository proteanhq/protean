"""Tests for Bucket F: Subscription Model Consistency.

Finding #16: Stream context passed as parameter, not mutable instance state.
Finding #17: DEFAULT_CONFIG tick_interval matches StreamSubscription behavior.
"""

from protean.server.subscription.profiles import (
    DEFAULT_CONFIG,
    PROFILE_DEFAULTS,
    SubscriptionProfile,
    SubscriptionType,
)
from protean.server.subscription.stream_subscription import StreamSubscription


# ---------------------------------------------------------------------------
# Finding #16: Stream context is per-batch, not global mutable state
# ---------------------------------------------------------------------------
class TestStreamContextParameter:
    def test_no_active_stream_attribute(self):
        """StreamSubscription no longer has a mutable _active_stream attribute."""
        assert not hasattr(StreamSubscription, "_active_stream")

    def test_process_batch_accepts_stream_parameter(self):
        """process_batch() accepts a stream keyword argument."""
        import inspect

        sig = inspect.signature(StreamSubscription.process_batch)
        assert "stream" in sig.parameters

    def test_acknowledge_message_accepts_stream_parameter(self):
        """_acknowledge_message() accepts a stream keyword argument."""
        import inspect

        sig = inspect.signature(StreamSubscription._acknowledge_message)
        assert "stream" in sig.parameters

    def test_move_to_dlq_accepts_stream_parameter(self):
        """move_to_dlq() accepts a stream keyword argument."""
        import inspect

        sig = inspect.signature(StreamSubscription.move_to_dlq)
        assert "stream" in sig.parameters

    def test_retry_message_accepts_stream_parameter(self):
        """_retry_message() accepts a stream keyword argument."""
        import inspect

        sig = inspect.signature(StreamSubscription._retry_message)
        assert "stream" in sig.parameters

    def test_handle_failed_message_accepts_stream_parameter(self):
        """handle_failed_message() accepts a stream keyword argument."""
        import inspect

        sig = inspect.signature(StreamSubscription.handle_failed_message)
        assert "stream" in sig.parameters

    def test_create_dlq_message_accepts_stream_parameter(self):
        """_create_dlq_message() accepts a stream keyword argument."""
        import inspect

        sig = inspect.signature(StreamSubscription._create_dlq_message)
        assert "stream" in sig.parameters


# ---------------------------------------------------------------------------
# Finding #17: DEFAULT_CONFIG tick_interval consistency
# ---------------------------------------------------------------------------
class TestTickIntervalConsistency:
    def test_default_config_tick_interval_is_zero(self):
        """DEFAULT_CONFIG tick_interval is 0, matching StreamSubscription's behavior."""
        assert DEFAULT_CONFIG["tick_interval"] == 0

    def test_production_stream_profiles_use_zero_tick_interval(self):
        """Non-debug STREAM-type profiles use tick_interval=0 (blocking reads provide pacing)."""
        for profile, defaults in PROFILE_DEFAULTS.items():
            if (
                defaults["subscription_type"] == SubscriptionType.STREAM
                and profile != SubscriptionProfile.DEBUG
            ):
                assert defaults["tick_interval"] == 0, (
                    f"{profile.value} profile has tick_interval={defaults['tick_interval']}, "
                    "expected 0 for STREAM subscription type"
                )

    def test_debug_profile_is_exception_with_tick_interval_one(self):
        """DEBUG profile uses tick_interval=1 for easier debugging."""
        debug_defaults = PROFILE_DEFAULTS[SubscriptionProfile.DEBUG]
        assert debug_defaults["tick_interval"] == 1

    def test_default_config_matches_production_profile_type(self):
        """DEFAULT_CONFIG subscription_type matches PRODUCTION profile."""
        assert DEFAULT_CONFIG["subscription_type"] == SubscriptionType.STREAM
        assert (
            PROFILE_DEFAULTS[SubscriptionProfile.PRODUCTION]["subscription_type"]
            == SubscriptionType.STREAM
        )
