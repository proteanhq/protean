import pytest

from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.domain.config import Config2, _default_config
from protean.exceptions import ConfigurationError
from protean.fields import Auto


def test_invalid_identity_strategy():
    domain = Domain()
    domain.config["identity_strategy"] = "invalid"

    class AutoTest(BaseAggregate):
        auto_field: Auto(identifier=True)

    domain.register(AutoTest)
    domain.init(traverse=False)
    with domain.domain_context():
        with pytest.raises(ConfigurationError) as exc:
            AutoTest()

        assert "Unknown Identity Strategy" in str(exc.value)


def test_error_on_no_identity_function_if_strategy_is_function():
    domain = Domain()
    domain.config["identity_strategy"] = "function"

    class AutoTest(BaseAggregate):
        auto_field: Auto(identifier=True)

    domain.register(AutoTest)
    with pytest.raises(ConfigurationError) as exc:
        domain.init(traverse=False)

    assert "no Identity Function is provided" in exc.value.args[0]["element"]


class TestPriorityLanesDefaults:
    """`server.priority_lanes` defaults must match the runtime `.get()`
    fallbacks in outbox_processor.py, stream_subscription.py, and dlq.py so
    that adding an explicit default is behavior-preserving."""

    def test_default_config_has_priority_lanes(self):
        config = _default_config()
        assert config["server"]["priority_lanes"] == {
            "enabled": False,
            "threshold": 0,
            "backfill_suffix": "backfill",
        }

    def test_partial_override_merges_with_defaults(self):
        """A user overriding only `enabled` must still get the default
        `threshold`/`backfill_suffix` — proving `_deep_merge` preserves the
        unset keys instead of replacing the whole sub-dict."""
        config = Config2.load_from_dict(
            {"server": {"priority_lanes": {"enabled": True}}}
        )

        assert config["server"]["priority_lanes"] == {
            "enabled": True,
            "threshold": 0,
            "backfill_suffix": "backfill",
        }

    @pytest.mark.no_test_domain
    def test_domain_with_no_priority_lanes_override_initializes(self):
        """The always-present default must pass `_validate_priority_lanes_config`
        for every domain, not just ones that configure it explicitly."""
        domain = Domain(__name__, "TestNoPriorityLanesOverride")

        class AutoTest(BaseAggregate):
            auto_field: Auto(identifier=True)

        domain.register(AutoTest)
        domain.init(traverse=False)  # Should not raise
