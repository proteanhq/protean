"""Coverage gaps in the subscription status collector (issue #1288).

Each class here pins one way the collector used to disagree with what the
Engine actually runs, or reported a healthy subscription when it knew nothing.
The shared theme: a monitoring surface that is confidently wrong is worse than
one that says "unknown", because an operator acts on it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from protean.server.subscription_status import (
    _classify_status,
    _collect_partitioned_stream_status,
    _is_partitioned_category,
    _outbox_processor_names,
)


def _domain(providers: dict, outbox_config: dict | None = None):
    domain = MagicMock()
    domain.providers = providers
    domain.config = {"outbox": outbox_config or {}}
    return domain


def _provider(managed: bool = True):
    provider = MagicMock()
    provider.managed = managed
    return provider


class TestOutboxProcessorNaming:
    """`total` counted processors the collector then failed to describe."""

    def test_one_row_per_managed_provider(self):
        names = _outbox_processor_names(_domain({"default": _provider()}))
        assert [n for n, _, _ in names] == ["outbox-processor-default-to-default"]

    def test_unmanaged_providers_get_no_row(self):
        """The Engine skips them, so reporting one invents a subscription."""
        domain = _domain({"default": _provider(), "readonly": _provider(managed=False)})
        providers = [p for _, p, _ in _outbox_processor_names(domain)]
        assert providers == ["default"]

    def test_external_brokers_get_their_own_processors(self):
        """The lane most likely to back up was previously invisible."""
        domain = _domain(
            {"default": _provider()},
            {"broker": "default", "external_brokers": ["partner", "analytics"]},
        )
        names = [n for n, _, _ in _outbox_processor_names(domain)]
        assert names == [
            "outbox-processor-default-to-default",
            "outbox-processor-default-to-partner-external",
            "outbox-processor-default-to-analytics-external",
        ]

    def test_external_processors_are_named_as_the_engine_names_them(self):
        """The `-external` suffix is what the Engine keys them by."""
        domain = _domain({"db": _provider()}, {"external_brokers": ["partner"]})
        names = [n for n, _, _ in _outbox_processor_names(domain)]
        assert "outbox-processor-db-to-partner-external" in names

    def test_external_brokers_cross_every_managed_provider(self):
        domain = _domain(
            {"a": _provider(), "b": _provider(), "skip": _provider(managed=False)},
            {"external_brokers": ["partner"]},
        )
        names = [n for n, _, _ in _outbox_processor_names(domain)]
        assert len(names) == 4  # 2 managed x (1 primary + 1 external)
        assert not any("skip" in n for n in names)

    def test_a_provider_without_a_managed_flag_counts_as_managed(self):
        provider = MagicMock(spec=[])  # no `managed` attribute at all
        names = _outbox_processor_names(_domain({"default": provider}))
        assert len(names) == 1


class TestUnknownLagIsNotReportedAsHealthy:
    """`lag = pending` made an unreadable lag classify as `ok`."""

    def test_none_lag_classifies_as_unknown(self):
        assert _classify_status(None, 0) == "unknown"

    def test_zero_lag_and_zero_pending_is_ok(self):
        assert _classify_status(0, 0) == "ok"

    def test_stream_fallback_leaves_lag_unknown(self):
        """Group readable, range read fails: previously `lag = pending` = 0 = ok."""
        from protean.server.subscription_status import _collect_stream_status

        domain = MagicMock()
        broker = MagicMock()
        redis = broker.redis_instance
        redis.xlen.return_value = 10
        redis.xinfo_groups.return_value = [
            {"name": "grp", "pending": 0, "last-delivered-id": "5-0", "consumers": 1}
        ]
        redis.xrange.side_effect = ConnectionError("cannot read range")
        broker._get_field_value.side_effect = lambda d, f, convert_to_int=False: d.get(
            f
        )
        domain.brokers.get.return_value = broker

        handler = MagicMock()
        handler.__name__ = "H"
        with patch(
            "protean.server.subscription_status._is_partitioned_category",
            return_value=False,
        ):
            status = _collect_stream_status(
                domain, "n", handler, "cat", consumer_group_name="grp"
            )

        assert status.lag is None
        assert status.status == "unknown"


@pytest.mark.no_test_domain
class TestPartitionedCategoryLag:
    """A `sequential_by` category publishes to `{category}:{key}`.

    Reading the base stream reports nothing, so a halted partition, which is
    the framework's own definition of a stuck subscription, produced no signal.
    """

    def _broker(self, partitions: dict[str, dict]):
        broker = MagicMock()
        broker._partition_keys.return_value = set(partitions)
        redis = broker.redis_instance
        redis.xlen.side_effect = lambda s: partitions.get(
            s.split(":", 1)[1] if ":" in s else s, {}
        ).get("len", 0)

        def _groups(stream):
            key = stream.split(":", 1)[1]
            info = partitions[key]
            return [
                {
                    "name": "grp",
                    "pending": info.get("pending", 0),
                    "lag": info.get("lag", 0),
                    "consumers": 1,
                }
            ]

        redis.xinfo_groups.side_effect = _groups
        broker._get_field_value.side_effect = lambda d, f, convert_to_int=False: d.get(
            f
        )
        return broker

    def _collect(self, partitions):
        domain = MagicMock()
        domain.brokers.get.return_value = self._broker(partitions)
        handler = MagicMock()
        handler.__name__ = "OrderHandler"
        return _collect_partitioned_stream_status(
            domain, "orders", handler, "order", "grp"
        )

    def test_lag_is_summed_across_partitions(self):
        status = self._collect({"a": {"lag": 3, "len": 10}, "b": {"lag": 4, "len": 5}})
        assert status.lag == 7
        assert status.status == "lagging"

    def test_one_halted_partition_is_visible(self):
        """The case that previously reported `unknown` and told nobody."""
        status = self._collect(
            {"a": {"lag": 0, "len": 10}, "stuck": {"lag": 500, "len": 500}}
        )
        assert status.lag == 500
        assert status.status == "lagging"

    def test_all_caught_up_is_ok_not_unknown(self):
        status = self._collect({"a": {"lag": 0, "len": 3}, "b": {"lag": 0, "len": 2}})
        assert status.lag == 0
        assert status.status == "ok"

    def test_pending_is_summed_too(self):
        status = self._collect(
            {"a": {"lag": 0, "pending": 2, "len": 5}, "b": {"lag": 0, "pending": 3}}
        )
        assert status.pending == 5

    def test_no_partitions_yet_is_zero_not_unknown(self):
        """Nothing published is genuinely zero lag, not unreadable lag."""
        status = self._collect({})
        assert status.lag == 0
        assert status.status == "ok"

    def test_partition_count_is_reported(self):
        status = self._collect({"a": {"lag": 0}, "b": {"lag": 0}, "c": {"lag": 0}})
        assert status.current_position == "3 partition(s)"

    def test_an_unreadable_partition_index_is_unknown(self):
        domain = MagicMock()
        broker = MagicMock()
        broker._partition_keys.side_effect = ConnectionError("redis down")
        domain.brokers.get.return_value = broker
        handler = MagicMock()
        handler.__name__ = "H"

        status = _collect_partitioned_stream_status(
            domain, "orders", handler, "order", "grp"
        )
        assert status.lag is None
        assert status.status == "unknown"

    def test_a_non_redis_broker_is_unknown_not_zero(self):
        domain = MagicMock()
        domain.brokers.get.return_value = MagicMock(spec=[])  # no redis_instance
        handler = MagicMock()
        handler.__name__ = "H"

        status = _collect_partitioned_stream_status(
            domain, "orders", handler, "order", "grp"
        )
        assert status.lag is None
        assert status.status == "unknown"


class TestPartitionDetection:
    """A category is partitioned only when both halves agree (ADR-0028 §8)."""

    def _domain(self, partition_keys):
        domain = MagicMock()
        domain._partition_keys = partition_keys
        return domain

    def test_category_without_sequential_by_is_not_partitioned(self):
        assert _is_partitioned_category(self._domain({}), "order") is False

    def test_declared_but_broker_cannot_partition(self):
        """`sequential_by` on the inline broker is a no-op, so read the base."""
        with patch(
            "protean.server.subscription.factory.broker_supports_partitioning",
            return_value=False,
        ):
            assert (
                _is_partitioned_category(self._domain({"order": "id"}), "order")
                is False
            )

    def test_declared_and_broker_partitions(self):
        with patch(
            "protean.server.subscription.factory.broker_supports_partitioning",
            return_value=True,
        ):
            assert (
                _is_partitioned_category(self._domain({"order": "id"}), "order") is True
            )

    def test_stream_collection_routes_to_the_partition_reader(self):
        from protean.server.subscription_status import _collect_stream_status

        domain = MagicMock()
        handler = MagicMock()
        handler.__name__ = "H"
        handler.__module__ = "tests.handlers"
        handler.__qualname__ = "H"
        sentinel = object()

        with (
            patch(
                "protean.server.subscription_status._is_partitioned_category",
                return_value=True,
            ),
            patch(
                "protean.server.subscription_status._collect_partitioned_stream_status",
                return_value=sentinel,
            ) as partitioned,
        ):
            result = _collect_stream_status(domain, "n", handler, "order")

        assert result is sentinel
        assert partitioned.called


class TestPartitionReadDegradesGracefully:
    def _domain_with(self, redis):
        broker = MagicMock()
        broker._partition_keys.return_value = {"a", "b"}
        broker.redis_instance = redis
        broker._get_field_value.side_effect = lambda d, f, convert_to_int=False: d.get(
            f
        )
        domain = MagicMock()
        domain.brokers.get.return_value = broker
        return domain

    def _collect(self, domain):
        handler = MagicMock()
        handler.__name__ = "H"
        return _collect_partitioned_stream_status(
            domain, "orders", handler, "order", "grp"
        )

    def test_a_partition_that_cannot_be_read_is_skipped(self):
        """One unreadable partition must not lose the others' lag."""
        redis = MagicMock()
        redis.xlen.return_value = 5

        def _groups(stream):
            if stream.endswith(":a"):
                raise ConnectionError("partition unreadable")
            return [{"name": "grp", "pending": 1, "lag": 9, "consumers": 1}]

        redis.xinfo_groups.side_effect = _groups
        status = self._collect(self._domain_with(redis))

        assert status.lag == 9
        assert status.pending == 1

    def test_a_group_belonging_to_another_consumer_is_ignored(self):
        redis = MagicMock()
        redis.xlen.return_value = 5
        redis.xinfo_groups.return_value = [
            "not-a-dict",
            {"name": "someone-else", "pending": 99, "lag": 99, "consumers": 1},
        ]
        status = self._collect(self._domain_with(redis))

        # No group matched, so nothing is known rather than zero.
        assert status.lag is None
        assert status.pending == 0


class TestPartitionLagRequiresARealReading:
    """Finding the consumer group is not the same as reading its lag.

    A broker without the native `lag` field (Redis before 7.0) reports groups
    fine but no lag. Treating "group found" as "lag known" made every partition
    contribute 0 and reported a caught-up subscription whose lag was never read,
    which is the exact failure this collector exists to remove.
    """

    def _collect(self, groups_per_partition):
        broker = MagicMock()
        broker._partition_keys.return_value = set(groups_per_partition)
        redis = broker.redis_instance
        redis.xlen.return_value = 10
        redis.xinfo_groups.side_effect = lambda stream: groups_per_partition[
            stream.split(":", 1)[1]
        ]
        broker._get_field_value.side_effect = lambda d, f, convert_to_int=False: d.get(
            f
        )
        domain = MagicMock()
        domain.brokers.get.return_value = broker
        handler = MagicMock()
        handler.__name__ = "H"
        return _collect_partitioned_stream_status(
            domain, "orders", handler, "order", "grp"
        )

    def test_group_without_a_lag_field_is_unknown_not_zero(self):
        status = self._collect({"a": [{"name": "grp", "pending": 0, "consumers": 1}]})
        assert status.lag is None
        assert status.status == "unknown"

    def test_pending_is_still_reported_when_lag_is_unknown(self):
        status = self._collect({"a": [{"name": "grp", "pending": 4, "consumers": 1}]})
        assert status.lag is None
        assert status.pending == 4

    def test_a_single_readable_partition_makes_the_total_known(self):
        status = self._collect(
            {
                "a": [{"name": "grp", "pending": 0, "consumers": 1}],
                "b": [{"name": "grp", "pending": 0, "lag": 6, "consumers": 1}],
            }
        )
        assert status.lag == 6
