"""The adapter manifest (tests/adapters.toml) and the PR lane that reads it.

The first class is the guard: it fails when an adapter module is in no manifest
entry, when a test marked for a "touched" adapter is outside that adapter's
paths, when a database, broker, event-store or cache entry leaves out a shared
module it loads through, or when an entry names a path, service or suite that does not exist, so
the PR lane cannot silently stop testing an adapter.
"""

import json
import os
import re
import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path
from unittest.mock import patch

import pytest
import typer
from _pytest.mark.expression import Expression
from typer.testing import CliRunner

from protean.cli import app
from protean.cli.test import (
    ADAPTER_LANES,
    ADAPTER_MANIFEST,
    CONFORMANCE_DEFAULT_ADAPTERS,
    CONFORMANCE_PORT_GROUPS,
    REPO_ROOT,
    TEST_CONFIGS,
    AdapterEntry,
    AdapterManifest,
    ConformanceRun,
    TestRunner,
    _registered_adapters,
    build_adapter_matrix,
    build_adapter_suites,
    build_conformance_suites,
    load_adapter_manifest,
    run_pr_lane,
)
from tests.conftest import OPT_IN_MARKERS
from tests.shared import POSTGRES_URI
from tests.support.adapter_markers import MARKERS_FILE

# The manifest and the PR lane are file and CLI work; none of it loads a domain.
pytestmark = pytest.mark.no_test_domain

ADAPTERS_SRC = REPO_ROOT / "src" / "protean" / "adapters"
TESTS_DIR = REPO_ROOT / "tests"
TEST_SUITE_ACTION = REPO_ROOT / ".github" / "actions" / "test-suite" / "action.yml"

# The opt-in markers that need an adapter's flag and, through it, its service.
ADAPTER_MARKERS = frozenset(OPT_IN_MARKERS) - {"slow", "pending"}

# The pytest options in a suite's command that take the next argument.
VALUE_OPTIONS = {"-m", "--port", "--adapter", "--adapter-config"}

# The tests that carry two adapter markers, as of the change that let one leg
# run them. The guard checks that collection still finds them.
DUAL_MARKED_FILES = {
    "tests/outbox/test_reconciliation.py",
    "tests/server/test_outbox_hold_back_repro.py",
    "tests/unit_of_work/test_stale_event_sourced_outbox.py",
}


@pytest.fixture(scope="module")
def manifest() -> AdapterManifest:
    return load_adapter_manifest()


def _entry(name: str, lane: str = "touched", **kwargs) -> AdapterEntry:
    fields: dict = {
        "leg": name,
        "services": [],
        "paths": [],
        "markers": [],
        "databases": [],
        "stores": [],
    }
    fields.update(kwargs)
    fields["conformance"] = [
        ConformanceRun(*pair.split(":")) for pair in kwargs.get("conformance", [])
    ]
    return AdapterEntry(name=name, lane=lane, **fields)


@pytest.fixture(scope="module")
def collected_markers(tmp_path_factory) -> dict[str, dict[str, list[str]]]:
    """The markers and marker-name keywords of every test under tests/.

    pytest collects tests/ in a child process, so the parent run's ``-m`` and
    flags do not change what it finds.
    """
    out = tmp_path_factory.mktemp("markers") / "markers.json"
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    env[MARKERS_FILE] = str(out)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "tests.support.adapter_markers",
            "--ignore=tests/support/",
            "tests",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def _pytest_args(command: list[str]) -> tuple[str | None, set[str], list[str]]:
    """The ``-m`` expression, the ``--<name>`` flags and the paths of a suite."""
    args = command[command.index("pytest") + 1 :]
    expression, flags, paths = None, set(), []
    values = iter(args)
    for arg in values:
        if arg in VALUE_OPTIONS:
            value = next(values)
            if arg == "-m":
                expression = value
        elif arg.startswith("-"):
            flags.add(arg.removeprefix("--"))
        else:
            paths.append(arg)
    return expression, flags, paths or ["tests"]


def _runs(command: list[str], nodeid: str, markers: set[str], needs: set[str]):
    """Whether ``command`` selects the test and passes a flag for each need."""
    expression, flags, paths = _pytest_args(command)
    selected = expression is None or Expression.compile(expression).evaluate(
        lambda name, **kwargs: name in markers
    )
    in_paths = any(
        nodeid == p or nodeid.startswith((p.rstrip("/") + "/", p + "::")) for p in paths
    )
    return selected and in_paths and needs <= flags


def _legs(adapters: list[AdapterEntry]) -> list[tuple[set[str], list[list[str]]]]:
    """The services and suite commands of each leg the runnable adapters form."""
    legs: dict[str, list[AdapterEntry]] = {}
    for entry in adapters:
        if entry.lane in ("pr", "touched"):
            legs.setdefault(entry.leg, []).append(entry)
    runner = TestRunner()
    return [
        (
            {s for e in entries for s in e.services},
            [s.command for s in build_adapter_suites(runner, entries)],
        )
        for entries in legs.values()
    ]


def _uncovered(
    collected: dict[str, dict[str, list[str]]], adapters: list[AdapterEntry]
) -> list[str]:
    """The tests with two adapter markers that no leg of ``adapters`` runs.

    A leg runs a test when one of its suites selects it and passes the flag of
    each adapter marker it carries, and the leg starts the services of the
    adapters that have those markers.
    """
    legs = _legs(adapters)
    services_of = {
        marker: {s for e in adapters if marker in e.markers for s in e.services}
        for marker in ADAPTER_MARKERS
    }

    uncovered = []
    for nodeid, names in collected.items():
        needs = ADAPTER_MARKERS & {*names["markers"], *names["keywords"]}
        if len(needs) < 2:
            continue
        services = {s for marker in needs for s in services_of[marker]}
        if not any(
            services <= leg_services
            and _leg_runs(commands, nodeid, set(names["markers"]), needs)
            for leg_services, commands in legs
        ):
            uncovered.append(f"{nodeid} {sorted(needs)}")
    return uncovered


def _leg_runs(
    commands: list[list[str]], nodeid: str, markers: set[str], needs: set[str]
) -> bool:
    """Whether one of a leg's suite commands runs the test."""
    return any(_runs(cmd, nodeid, markers, needs) for cmd in commands)


class TestManifestIsCurrent:
    def test_every_adapter_module_is_in_an_entry(self, manifest):
        modules = sorted(
            p.relative_to(REPO_ROOT).as_posix() for p in ADAPTERS_SRC.rglob("*.py")
        )
        missing = [
            m for m in modules if not any(e.matches(m) for e in manifest.adapters)
        ]
        assert not missing, (
            f"Add these to an entry in {ADAPTER_MANIFEST.name}, so a PR that "
            f"changes them runs their tests: {missing}"
        )

    def test_every_marked_test_is_in_its_adapters_paths(self, manifest):
        # A "touched" leg runs only when the PR changes one of its paths, and
        # CORE skips its marked tests. So a marked test outside the paths would
        # run on no PR that edits it.
        test_files = sorted(TESTS_DIR.rglob("*.py"))
        missing = []
        for entry in manifest.adapters:
            if entry.lane != "touched":
                continue
            for marker in entry.markers:
                mark = re.compile(rf"pytest\.mark\.{marker}\b")
                missing += [
                    f"{entry.name}: {rel}"
                    for f in test_files
                    if not entry.matches(rel := f.relative_to(REPO_ROOT).as_posix())
                    and mark.search(f.read_text(encoding="utf-8"))
                ]
        assert not missing, (
            f"Add these tests to their entry's paths in {ADAPTER_MANIFEST.name}, "
            f"so a PR that changes them runs them: {missing}"
        )

    @pytest.mark.parametrize(
        "suite, shared",
        [
            (
                "databases",
                [
                    "src/protean/adapters/database/__init__.py",
                    "src/protean/infra/registry.py",
                    "src/protean/port/dao.py",
                    "src/protean/port/database.py",
                ],
            ),
            (
                "stores",
                [
                    "src/protean/adapters/event_store/__init__.py",
                    "src/protean/infra/event_store.py",
                    "src/protean/infra/registry.py",
                    "src/protean/port/event_store.py",
                ],
            ),
        ],
    )
    def test_every_adapter_includes_the_shared_modules_it_runs_on(
        self, manifest, suite, shared
    ):
        # Every database adapter loads through Databases and the DAO and
        # provider ports, and every event store through the EventStore service
        # and its port. Every database and event store is resolved by its
        # adapter registry. A change to one of them must run every such
        # adapter.
        missing = [
            f"{entry.name}: {path}"
            for entry in manifest.adapters
            if getattr(entry, suite)
            for path in shared
            if not entry.matches(path)
        ]
        assert not missing, (
            f"Add these shared modules to their entry's paths in "
            f"{ADAPTER_MANIFEST.name}: {missing}"
        )

    def test_every_broker_adapter_includes_the_shared_modules_it_runs_on(
        self, manifest
    ):
        # Brokers have no capability suite, so an entry counts as a broker
        # adapter when it names a broker module. Every broker loads through the
        # Brokers collection, which resolves its class through the registry,
        # and every call goes through the Broker service to the broker port.
        shared = [
            "src/protean/adapters/broker/__init__.py",
            "src/protean/infra/broker.py",
            "src/protean/infra/registry.py",
            "src/protean/port/broker.py",
        ]
        broker_entries = [
            entry
            for entry in manifest.adapters
            if any(p.startswith("src/protean/adapters/broker/") for p in entry.paths)
        ]
        assert {e.name for e in broker_entries} >= {
            "memory",
            "redis-broker",
            "redis-pubsub",
        }
        missing = [
            f"{entry.name}: {path}"
            for entry in broker_entries
            for path in shared
            if not entry.matches(path)
        ]
        assert not missing, (
            f"Add these shared modules to their entry's paths in "
            f"{ADAPTER_MANIFEST.name}: {missing}"
        )

    def test_every_cache_adapter_includes_the_shared_modules_it_runs_on(self, manifest):
        # Caches have no capability suite, so an entry counts as a cache
        # adapter when it names a cache module. Every cache loads through the
        # Caches collection, which resolves its class through the registry,
        # and every call goes through the Cache service to the cache ports.
        shared = [
            "src/protean/adapters/cache/__init__.py",
            "src/protean/infra/cache.py",
            "src/protean/infra/registry.py",
            "src/protean/port/cache.py",
            "src/protean/port/health.py",
        ]
        cache_entries = [
            entry
            for entry in manifest.adapters
            if any(p.startswith("src/protean/adapters/cache/") for p in entry.paths)
        ]
        assert {e.name for e in cache_entries} >= {"memory", "redis-cache"}
        missing = [
            f"{entry.name}: {path}"
            for entry in cache_entries
            for path in shared
            if not entry.matches(path)
        ]
        assert not missing, (
            f"Add these shared modules to their entry's paths in "
            f"{ADAPTER_MANIFEST.name}: {missing}"
        )

    def test_every_path_exists(self, manifest):
        paths = [p for e in manifest.adapters for p in e.paths] + manifest.trigger_all
        missing = [p for p in paths if not (REPO_ROOT / p).exists()]
        assert not missing, f"{ADAPTER_MANIFEST.name} names missing paths: {missing}"

    def test_every_conformance_suite_is_in_its_adapters_paths(self, manifest):
        # A "touched" leg runs only when the PR changes one of its paths, so a
        # suite outside them would run on no PR that edits it.
        runs = [(e, run) for e in manifest.adapters for run in e.conformance]
        assert runs
        missing = []
        for entry, run in runs:
            folder = f"tests/conformance/{run.port}/"
            assert (REPO_ROOT / folder).is_dir()
            if folder not in entry.paths:
                missing.append((entry.name, folder))
        assert not missing, f"Add these folders to the entries' paths: {missing}"

    def test_every_lane_is_known(self, manifest):
        assert {e.lane for e in manifest.adapters} <= set(ADAPTER_LANES)

    def test_every_service_is_started_by_the_test_suite_action(self, manifest):
        action = TEST_SUITE_ACTION.read_text(encoding="utf-8")
        services = {s for e in manifest.adapters for s in e.services}
        missing = [s for s in sorted(services) if f"--name {s} " not in action]
        assert not missing, f"The test-suite action starts no container for {missing}"

    def test_every_marker_is_registered(self, manifest):
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
        registered = {
            m.split(":")[0]
            for m in pyproject["tool"]["pytest"]["ini_options"]["markers"]
        }
        markers = {m for e in manifest.adapters for m in e.markers}
        assert markers <= registered

    def test_every_suite_is_one_full_runs(self, manifest):
        for entry in manifest.adapters:
            assert set(entry.databases) <= set(TEST_CONFIGS["databases"])
            assert set(entry.stores) <= set(TEST_CONFIGS["eventstores"])

    def test_every_runnable_adapter_runs_something(self, manifest):
        for entry in manifest.adapters:
            if entry.lane in ("pr", "touched"):
                assert (
                    entry.markers
                    or entry.databases
                    or entry.stores
                    or entry.conformance
                )

    def test_the_pr_lane_is_postgres_and_redis(self, manifest):
        assert {e.leg for e in manifest.pr_adapters()} == {"postgresql", "redis"}

    def test_every_test_with_two_adapter_markers_runs_in_a_leg(
        self, manifest, collected_markers
    ):
        # tests/conftest.py skips a test for each adapter marker whose flag is
        # missing, so a test with two markers runs only in a leg that passes
        # both flags and starts both services.
        found = {
            nodeid.split("::")[0]
            for nodeid, names in collected_markers.items()
            if len(ADAPTER_MARKERS & {*names["markers"], *names["keywords"]}) > 1
        }
        assert found >= DUAL_MARKED_FILES
        uncovered = _uncovered(collected_markers, manifest.adapters)
        assert not uncovered, (
            f"No leg runs these tests: add their other markers to an entry's "
            f"enables in {ADAPTER_MANIFEST.name}, and those markers' services "
            f"to its services: {uncovered}"
        )


class TestDualMarkedGuard:
    TEST = "tests/x/test_both.py::test_it"
    BOTH = {TEST: {"markers": ["message_db", "postgresql"], "keywords": []}}

    def adapters(
        self, enables: list[str] | None = None, services: list[str] | None = None
    ) -> list[AdapterEntry]:
        return [
            _entry("postgresql", markers=["postgresql"], services=["postgres"]),
            _entry(
                "message-db",
                markers=["message_db"],
                services=services or ["message-db"],
                enables=enables or [],
            ),
        ]

    def test_a_test_no_leg_enables_is_uncovered(self):
        assert _uncovered(self.BOTH, self.adapters()) == [
            f"{self.TEST} ['message_db', 'postgresql']"
        ]

    def test_a_leg_with_the_flag_but_not_the_service_is_not_enough(self):
        adapters = self.adapters(enables=["postgresql"])
        assert _uncovered(self.BOTH, adapters) == [
            f"{self.TEST} ['message_db', 'postgresql']"
        ]

    def test_a_leg_with_the_flag_and_the_service_covers_it(self):
        adapters = self.adapters(
            enables=["postgresql"], services=["message-db", "postgres"]
        )
        assert _uncovered(self.BOTH, adapters) == []

    def test_an_off_entry_covers_nothing(self):
        adapters = self.adapters(
            enables=["postgresql"], services=["message-db", "postgres"]
        )
        adapters[1].lane = "off"
        assert _uncovered(self.BOTH, adapters) != []

    def test_a_folder_keyword_needs_its_flag_too(self):
        # tests/conftest.py skips by keyword, so a test under a redis/ folder
        # needs --redis without the redis marker.
        collected = {
            "tests/redis/test_x.py::test_it": {
                "markers": ["postgresql"],
                "keywords": ["postgresql", "redis"],
            }
        }
        adapters = [
            _entry("postgresql", markers=["postgresql"], services=["postgres"]),
            _entry("redis", markers=["redis"], services=["redis"]),
        ]
        assert _uncovered(collected, adapters) != []
        adapters[0].enables = ["redis"]
        adapters[0].services = ["postgres", "redis"]
        assert _uncovered(collected, adapters) == []

    def test_a_test_with_one_adapter_marker_is_left_to_its_own_leg(self):
        collected = {self.TEST: {"markers": ["postgresql", "slow"], "keywords": []}}
        assert _uncovered(collected, self.adapters()) == []

    def test_a_run_on_other_paths_does_not_cover_it(self):
        command = ["pytest", "-m", "message_db", "--message_db", "--postgresql"]
        needs = {"message_db", "postgresql"}
        assert _runs([*command, "tests"], self.TEST, needs, needs)
        assert _runs([*command, "tests/x/"], self.TEST, needs, needs)
        assert not _runs([*command, "tests/xy"], self.TEST, needs, needs)
        assert not _runs([*command, "tests/y"], self.TEST, needs, needs)


class TestLoadAdapterManifest:
    def test_leg_defaults_to_the_entry_name(self, tmp_path):
        path = tmp_path / "adapters.toml"
        path.write_text('[adapters.solo]\nlane = "touched"\n')
        (entry,) = load_adapter_manifest(path).adapters
        assert entry.leg == "solo"
        assert entry.services == [] and entry.paths == []

    def test_an_unknown_lane_is_rejected(self, tmp_path):
        path = tmp_path / "adapters.toml"
        path.write_text('[adapters.odd]\nlane = "sometimes"\n')
        with pytest.raises(ValueError, match="lane 'sometimes'"):
            load_adapter_manifest(path)

    def test_an_unknown_key_is_rejected(self, tmp_path):
        path = tmp_path / "adapters.toml"
        path.write_text('[adapters.broker]\nlane = "touched"\nbrokers = ["REDIS"]\n')
        with pytest.raises(
            ValueError,
            match=r"Adapter 'broker' in adapters\.toml has unknown keys \['brokers'\]",
        ):
            load_adapter_manifest(path)

    def write(self, tmp_path, conformance: str) -> Path:
        path = tmp_path / "adapters.toml"
        path.write_text(
            f'[adapters.store]\nlane = "touched"\nconformance = {conformance}\n'
        )
        return path

    def test_conformance_pairs_are_read(self, tmp_path):
        path = self.write(tmp_path, '["event_store:message_db"]')
        (entry,) = load_adapter_manifest(path).adapters
        assert entry.conformance == [ConformanceRun("event_store", "message_db")]

    def test_a_conformance_table_is_read_with_its_config_and_label(self, tmp_path):
        path = self.write(
            tmp_path,
            '[{ port = "event_store", adapter = "sql", '
            'config = { database_uri = "postgresql://h/db" } }]',
        )
        (entry,) = load_adapter_manifest(path).adapters
        assert entry.conformance == [
            ConformanceRun(
                "event_store",
                "sql",
                config='{"database_uri": "postgresql://h/db"}',
                label="store",
            )
        ]

    def test_a_conformance_table_without_config_has_none(self, tmp_path):
        path = self.write(tmp_path, '[{ port = "event_store", adapter = "sql" }]')
        (entry,) = load_adapter_manifest(path).adapters
        assert entry.conformance == [
            ConformanceRun("event_store", "sql", config=None, label="store")
        ]

    def test_a_conformance_table_with_an_unknown_key_is_rejected(self, tmp_path):
        path = self.write(
            tmp_path, '[{ port = "event_store", adapter = "sql", uri = "x" }]'
        )
        with pytest.raises(
            ValueError, match=r"Adapter 'store'.*unknown keys \['uri'\]"
        ):
            load_adapter_manifest(path)

    def test_a_conformance_config_that_is_not_a_table_is_rejected(self, tmp_path):
        path = self.write(
            tmp_path, '[{ port = "event_store", adapter = "sql", config = "x" }]'
        )
        with pytest.raises(
            ValueError, match="Adapter 'store' has conformance config 'x'"
        ):
            load_adapter_manifest(path)

    @pytest.mark.parametrize(
        "table, message",
        [
            ('{ adapter = "sql" }', "'<port>:<adapter>'"),
            ('{ port = "event_store" }', "'<port>:<adapter>'"),
            ('{ port = "queue", adapter = "sql" }', "port 'queue'"),
            ('{ port = "event_store", adapter = "memory" }', "core run already runs"),
            ('{ port = "event_store", adapter = "nope" }', "adapter 'nope'"),
        ],
    )
    def test_a_conformance_table_gets_the_pair_checks(self, tmp_path, table, message):
        path = self.write(tmp_path, f"[{table}]")
        with pytest.raises(ValueError, match=f"Adapter 'store'.*{message}"):
            load_adapter_manifest(path)

    def test_two_runs_with_one_suite_name_are_rejected(self, tmp_path):
        path = self.write(
            tmp_path,
            '[{ port = "event_store", adapter = "sql", config = { a = 1 } }, '
            '{ port = "event_store", adapter = "sql", config = { a = 2 } }]',
        )
        with pytest.raises(
            ValueError,
            match=r"Adapter 'store' lists two conformance runs named "
            r"\['Conformance: event_store/sql \(store\)'\]",
        ):
            load_adapter_manifest(path)

    def test_a_pair_and_a_table_of_one_adapter_are_both_kept(self, tmp_path):
        path = self.write(
            tmp_path, '["event_store:sql", { port = "event_store", adapter = "sql" }]'
        )
        (entry,) = load_adapter_manifest(path).adapters
        assert [run.name for run in entry.conformance] == [
            "Conformance: event_store/sql",
            "Conformance: event_store/sql (store)",
        ]

    def test_a_conformance_config_json_cannot_write_is_rejected(self, tmp_path):
        path = self.write(
            tmp_path,
            '[{ port = "event_store", adapter = "sql", '
            "config = { at = 2031-03-04T12:30:00Z } }]",
        )
        with pytest.raises(
            ValueError, match=r"Adapter 'store' has conformance config .* JSON cannot"
        ):
            load_adapter_manifest(path)

    def test_an_entry_without_conformance_lists_none(self, tmp_path):
        path = tmp_path / "adapters.toml"
        path.write_text('[adapters.solo]\nlane = "touched"\n')
        (entry,) = load_adapter_manifest(path).adapters
        assert entry.conformance == []

    @pytest.mark.parametrize(
        "pair", ["event_store", "event_store:", ":message_db", "event_store-memory"]
    )
    def test_a_pair_without_a_port_and_an_adapter_is_rejected(self, tmp_path, pair):
        path = self.write(tmp_path, f'["{pair}"]')
        with pytest.raises(ValueError, match="Adapter 'store'.*'<port>:<adapter>'"):
            load_adapter_manifest(path)

    @pytest.mark.parametrize(
        "value",
        [
            "false",
            "0",
            '""',
            "{}",
            '{ "event_store:message_db" = 1 }',
            '"event_store:message_db"',
        ],
    )
    def test_a_conformance_value_that_is_not_a_list_is_rejected(self, tmp_path, value):
        path = self.write(tmp_path, value)
        with pytest.raises(ValueError, match="Adapter 'store' has conformance .*list"):
            load_adapter_manifest(path)

    @pytest.mark.parametrize(
        "pair",
        ["event_store:memory", "database:memory", "cache:memory", "broker:inline"],
    )
    def test_a_pair_naming_the_default_adapter_is_rejected(self, tmp_path, pair):
        path = self.write(tmp_path, f'["{pair}"]')
        with pytest.raises(ValueError, match="Adapter 'store'.*core run already runs"):
            load_adapter_manifest(path)

    def test_the_default_adapters_match_the_conformance_plugin(self):
        from tests.conformance.conftest import DEFAULT_ADAPTERS

        assert CONFORMANCE_DEFAULT_ADAPTERS == DEFAULT_ADAPTERS

    def test_an_empty_entry_point_group_says_to_sync(self, tmp_path):
        path = self.write(tmp_path, '["event_store:message_db"]')
        with patch("protean.cli.test._registered_adapters", return_value=set()):
            with pytest.raises(
                ValueError,
                match=r"Adapter 'store'.*'event_store:message_db'.*protean\.event_stores.*uv sync",
            ):
                load_adapter_manifest(path)

    def test_a_pair_that_is_not_a_string_is_rejected(self, tmp_path):
        path = self.write(tmp_path, "[1]")
        with pytest.raises(ValueError, match="Adapter 'store'.*'<port>:<adapter>'"):
            load_adapter_manifest(path)

    def test_an_unknown_port_is_rejected(self, tmp_path):
        path = self.write(tmp_path, '["queue:x"]')
        with pytest.raises(ValueError, match="Adapter 'store'.*port 'queue'"):
            load_adapter_manifest(path)

    def test_an_unregistered_adapter_is_rejected(self, tmp_path):
        path = self.write(tmp_path, '["event_store:message_db"]')
        with patch(
            "protean.cli.test._registered_adapters", return_value={"memory"}
        ) as registered:
            with pytest.raises(
                ValueError,
                match=r"Adapter 'store'.*'message_db'.*protean\.event_stores",
            ):
                load_adapter_manifest(path)
        registered.assert_called_once_with("protean.event_stores")

    @pytest.mark.parametrize(
        "port,present,absent",
        [
            ("database", {"memory", "sqlite"}, {"inline", "message_db", "redis"}),
            ("broker", {"inline", "redis_pubsub"}, {"memory"}),
            ("cache", {"memory", "redis"}, {"inline", "sqlite", "message_db"}),
            ("event_store", {"memory", "message_db"}, {"inline", "sqlite", "redis"}),
        ],
    )
    def test_each_port_reads_the_group_its_adapters_register_in(
        self, port, present, absent
    ):
        # Each row names adapters that only one group holds, so a port mapped
        # to another port's group fails here.
        registered = _registered_adapters(CONFORMANCE_PORT_GROUPS[port])
        assert present <= registered
        assert not absent & registered

    def test_the_real_manifest_loads_without_importing_an_adapter(self):
        # Importing protean.cli.test already imports some adapter modules, so
        # the check is that no entry point is loaded at all.
        with patch.object(
            metadata.EntryPoint, "load", side_effect=AssertionError("loaded")
        ):
            manifest = load_adapter_manifest()
        names = [run.name for e in manifest.adapters for run in e.conformance]
        assert names == [
            "Conformance: event_store/sql (postgresql)",
            "Conformance: broker/redis",
            "Conformance: broker/redis_pubsub",
            "Conformance: cache/redis",
            "Conformance: event_store/sql",
            "Conformance: event_store/message_db",
        ]

    def write_enables(self, tmp_path, enables: str, markers: str = '["redis"]'):
        path = tmp_path / "adapters.toml"
        path.write_text(
            '[adapters.pg]\nlane = "pr"\nmarkers = ["postgresql"]\n'
            f'[adapters.cache]\nlane = "pr"\nmarkers = {markers}\n'
            f"enables = {enables}\n"
        )
        return path

    def test_enables_is_read(self, tmp_path):
        _, cache = load_adapter_manifest(
            self.write_enables(tmp_path, '["postgresql"]')
        ).adapters
        assert cache.enables == ["postgresql"]

    def test_an_entry_without_enables_enables_none(self, tmp_path):
        path = tmp_path / "adapters.toml"
        path.write_text('[adapters.solo]\nlane = "touched"\nmarkers = ["redis"]\n')
        (entry,) = load_adapter_manifest(path).adapters
        assert entry.enables == []

    @pytest.mark.parametrize(
        "enables, markers, message",
        [
            ('["mysql"]', '["redis"]', "Adapter 'cache' enables 'mysql', which is no"),
            (
                '["redis"]',
                '["redis"]',
                "Adapter 'cache' enables its own marker 'redis'",
            ),
            ('"postgresql"', '["redis"]', "Adapter 'cache' has enables 'postgresql'"),
            ("[1]", '["redis"]', r"Adapter 'cache' has enables \[1\]"),
            ('["postgresql"]', "[]", "Adapter 'cache' has enables but no markers"),
        ],
    )
    def test_a_bad_enables_is_rejected(self, tmp_path, enables, markers, message):
        with pytest.raises(ValueError, match=message):
            load_adapter_manifest(self.write_enables(tmp_path, enables, markers))

    def test_a_manifest_without_triggers_has_none(self, tmp_path):
        path = tmp_path / "adapters.toml"
        path.write_text("")
        loaded = load_adapter_manifest(path)
        assert loaded.adapters == [] and loaded.trigger_all == []


class TestSelect:
    @pytest.fixture
    def small(self) -> AdapterManifest:
        return AdapterManifest(
            adapters=[
                _entry("core-thing", lane="core", paths=["src/core.py"]),
                _entry("always", lane="pr", paths=["src/always.py"]),
                _entry("es", paths=["src/es.py", "tests/es/"]),
                _entry("sql", paths=["src/sql.py"]),
                _entry("mail", lane="off", paths=["src/mail.py"]),
            ],
            trigger_all=["uv.lock", ".github/actions/"],
        )

    def names(self, adapters):
        return [e.name for e in adapters]

    def test_an_unrelated_change_runs_only_the_pr_lane(self, small):
        assert self.names(small.select(["docs/index.md", "src/core.py"])) == ["always"]

    def test_a_touched_adapter_runs_when_its_file_changes(self, small):
        assert self.names(small.select(["src/es.py"])) == ["always", "es"]

    def test_a_folder_path_matches_anything_under_it(self, small):
        assert self.names(small.select(["tests/es/deep/test_x.py"])) == ["always", "es"]

    def test_a_folder_path_does_not_match_a_sibling_prefix(self, small):
        assert self.names(small.select(["tests/es_other.py"])) == ["always"]

    def test_a_trigger_all_path_runs_every_leg_but_core_and_off(self, small):
        assert self.names(small.select(["uv.lock"])) == ["always", "es", "sql"]
        assert self.names(small.select([".github/actions/x/action.yml"])) == [
            "always",
            "es",
            "sql",
        ]

    def test_an_off_adapter_never_runs(self, small):
        assert "mail" not in self.names(small.select(["src/mail.py"]))

    @pytest.mark.parametrize(
        "changed",
        [
            "src/protean/adapters/event_store/message_db.py",
            "tests/conformance/event_store/test_placeholder.py",
            "tests/conformance/__init__.py",
            "tests/conformance/flag_coverage.py",
        ],
    )
    def test_the_real_manifest_runs_message_db_on_an_event_store_change(
        self, manifest, changed
    ):
        assert "message-db" in {e.name for e in manifest.select([changed])}

    def test_the_real_manifest_runs_every_dialect_on_a_sqlalchemy_change(
        self, manifest
    ):
        legs = {
            e.leg
            for e in manifest.select(["src/protean/adapters/database/sqlalchemy.py"])
        }
        assert legs == {"postgresql", "redis", "sqlite", "mssql", "mysql"}


class TestResolve:
    def test_by_adapter_name(self, manifest):
        assert [e.name for e in manifest.resolve(["elasticsearch"])] == [
            "elasticsearch"
        ]

    def test_a_leg_name_selects_every_adapter_in_it(self, manifest):
        assert {e.name for e in manifest.resolve(["redis"])} == {
            "redis-broker",
            "redis-pubsub",
            "redis-cache",
        }

    def test_repeats_are_dropped(self, manifest):
        assert len(manifest.resolve(["redis", "redis-cache"])) == 3

    @pytest.mark.parametrize("name", ["nope", "memory"], ids=["unknown", "core"])
    def test_an_unknown_or_core_name_is_rejected(self, manifest, name):
        with pytest.raises(typer.BadParameter, match="is not an adapter or leg"):
            manifest.resolve([name])

    def test_an_off_name_is_rejected(self):
        manifest = AdapterManifest(
            adapters=[_entry("es"), _entry("mail", lane="off")],
            trigger_all=[],
        )
        with pytest.raises(typer.BadParameter, match="is not an adapter or leg"):
            manifest.resolve(["mail"])


class TestBuildAdapterMatrix:
    def test_adapters_in_one_leg_share_it_and_its_services(self):
        matrix = build_adapter_matrix(
            [
                _entry("a", leg="redis", services=["redis"]),
                _entry("b", leg="redis", services=["redis"]),
                _entry("c", services=["mysql", "mariadb"]),
                _entry("d"),
            ]
        )
        assert matrix == {
            "include": [
                {
                    "leg": "redis",
                    "adapters": "a b",
                    "services": "redis",
                    "test-args": "-c PR --no-core -a a -a b",
                },
                {
                    "leg": "c",
                    "adapters": "c",
                    "services": "mysql mariadb",
                    "test-args": "-c PR --no-core -a c",
                },
                {
                    "leg": "d",
                    "adapters": "d",
                    "services": "",
                    "test-args": "-c PR --no-core -a d",
                },
            ]
        }


class TestBuildAdapterSuites:
    def test_the_redis_leg_runs_the_marker_once(self, manifest):
        suites = build_adapter_suites(TestRunner(), manifest.resolve(["redis"]))
        assert [s.name for s in suites] == [
            "Marker: redis",
            "Conformance: broker/redis",
            "Conformance: broker/redis_pubsub",
            "Conformance: cache/redis",
        ]

    def test_the_redis_marker_run_also_enables_postgresql(self, manifest):
        (marker, *_) = build_adapter_suites(TestRunner(), manifest.resolve(["redis"]))
        assert marker.command[-5:] == [
            "-m",
            "redis",
            "--redis",
            "--postgresql",
            "tests",
        ]

    def test_the_message_db_marker_run_also_enables_postgresql_and_sqlite(
        self, manifest
    ):
        (marker, *_) = build_adapter_suites(
            TestRunner(), manifest.resolve(["message-db"])
        )
        assert marker.name == "Marker: message_db"
        assert marker.command[-6:] == [
            "-m",
            "message_db",
            "--message_db",
            "--postgresql",
            "--sqlite",
            "tests",
        ]

    def test_a_shared_marker_run_passes_the_flags_of_every_entry(self):
        # Only the first suite of a name is kept, so the flags enabled by the
        # second entry must reach it.
        entries = [
            _entry("a", leg="r", markers=["redis"]),
            _entry("b", leg="r", markers=["redis"], enables=["postgresql"]),
            _entry("c", leg="r", markers=["redis"], enables=["sqlite", "postgresql"]),
        ]
        (suite,) = build_adapter_suites(TestRunner(), entries)
        assert suite.command[-6:] == [
            "-m",
            "redis",
            "--redis",
            "--postgresql",
            "--sqlite",
            "tests",
        ]

    def test_suites_are_coverage_wrapped_and_select_their_tests(self):
        runner = TestRunner()
        entry = _entry(
            "x",
            markers=["postgresql"],
            databases=["POSTGRESQL"],
            stores=["MESSAGE_DB"],
        )
        by_name = {s.name: s.command for s in build_adapter_suites(runner, [entry])}

        marker = by_name["Marker: postgresql"]
        assert marker[:4] == ["coverage", "run", "--parallel-mode", "-m"]
        assert marker[-3:] == ["postgresql", "--postgresql", "tests"]

        database = by_name["Database: POSTGRESQL"]
        assert database[-1] == "--db=POSTGRESQL"
        assert runner.get_database_marker_expression("POSTGRESQL") in database

        store = by_name["Event Store: MESSAGE_DB"]
        assert store[-3:] == ["-m", "eventstore", "--store=MESSAGE_DB"]

    def test_the_message_db_leg_runs_the_event_store_conformance_suite(self, manifest):
        runner = TestRunner()
        suites = build_adapter_suites(runner, manifest.resolve(["message-db"]))
        assert [s.name for s in suites] == [
            "Marker: message_db",
            "Event Store: MESSAGE_DB",
            "Conformance: event_store/message_db",
        ]
        assert suites[-1].command == runner.build_coverage_command(
            [
                "pytest",
                "--cache-clear",
                "--ignore=tests/support/",
                "tests/conformance/event_store",
                "--port",
                "event_store",
                "--adapter",
                "message_db",
            ]
        )

    def test_a_conformance_pair_runs_once_across_adapters(self):
        entries = [
            _entry("a", conformance=["event_store:message_db"]),
            _entry("b", conformance=["event_store:message_db", "cache:redis"]),
        ]
        suites = build_conformance_suites(TestRunner(), entries)
        assert [s.name for s in suites] == [
            "Conformance: event_store/message_db",
            "Conformance: cache/redis",
        ]

    def test_the_message_db_conformance_suite_shares_the_store_lock(self):
        entries = [_entry("a", conformance=["event_store:message_db", "cache:redis"])]
        message_db, redis = build_conformance_suites(TestRunner(), entries)
        assert message_db.shared_database == "message_db"
        assert redis.shared_database is None

    def test_a_conformance_suite_takes_the_lock_of_its_adapters_database(self):
        # The lock comes from SHARED_DATABASES, so a database suite on
        # PostgreSQL never runs beside "Database: POSTGRESQL".
        entries = [_entry("a", conformance=["database:postgresql"])]
        (suite,) = build_conformance_suites(TestRunner(), entries)
        assert suite.shared_database == "postgresql"

    def test_a_conformance_table_passes_its_config_and_takes_its_label_lock(self):
        run = ConformanceRun(
            "event_store", "sql", config='{"database_uri": "x"}', label="postgresql"
        )
        entry = _entry("postgresql")
        entry.conformance = [run]
        runner = TestRunner()
        (suite,) = build_conformance_suites(runner, [entry])
        assert suite.name == "Conformance: event_store/sql (postgresql)"
        assert suite.shared_database == "postgresql"
        assert suite.command == runner.build_coverage_command(
            [
                "pytest",
                "--cache-clear",
                "--ignore=tests/support/",
                "tests/conformance/event_store",
                "--port",
                "event_store",
                "--adapter",
                "sql",
                "--adapter-config",
                '{"database_uri": "x"}',
            ]
        )

    def test_one_adapter_on_two_databases_builds_two_suites(self, manifest):
        suites = build_conformance_suites(
            TestRunner(), manifest.resolve(["sqlite", "postgresql"])
        )
        by_name = {s.name: s for s in suites}
        assert set(by_name) == {
            "Conformance: event_store/sql",
            "Conformance: event_store/sql (postgresql)",
        }
        assert by_name["Conformance: event_store/sql"].shared_database is None
        assert "--adapter-config" not in by_name["Conformance: event_store/sql"].command
        postgresql = by_name["Conformance: event_store/sql (postgresql)"]
        assert postgresql.shared_database == "postgresql"
        config = postgresql.command[postgresql.command.index("--adapter-config") + 1]
        # The PostgreSQL service the database suites use.
        assert json.loads(config) == {"database_uri": POSTGRES_URI}

    def test_an_adapter_without_conformance_pairs_builds_no_suite(self):
        suites = build_adapter_suites(TestRunner(), [_entry("x", markers=["redis"])])
        assert [s.name for s in suites] == ["Marker: redis"]


class TestRunPrLane:
    def test_runs_core_under_coverage_then_the_adapters(self, manifest):
        runner = TestRunner()
        with patch.object(runner, "run_command", return_value=0) as run:
            code = run_pr_lane(runner, manifest.resolve(["postgresql"]), "4")
        commands = [c.args[0] for c in run.call_args_list]
        assert code == 0
        assert commands[0] == ["coverage", "erase"]
        assert commands[1] == runner.build_coverage_command(
            runner.build_core_command("4")
        )
        assert commands[2][-1] == "tests" and "--postgresql" in commands[2]
        assert commands[3][-1] == "--db=POSTGRESQL"
        assert ["coverage", "combine"] in commands

    def test_the_message_db_lane_runs_the_conformance_suite(self, manifest):
        runner = TestRunner()
        with patch.object(runner, "run_command", return_value=0) as run:
            run_pr_lane(runner, manifest.resolve(["message-db"]), None)
        commands = [c.args[0] for c in run.call_args_list]
        conformance = [c for c in commands if "tests/conformance/event_store" in c]
        assert len(conformance) == 1
        assert conformance[0][:4] == ["coverage", "run", "--parallel-mode", "-m"]
        assert conformance[0][-4:] == [
            "--port",
            "event_store",
            "--adapter",
            "message_db",
        ]

    def test_no_core_workers_skips_core(self):
        runner = TestRunner()
        with patch.object(runner, "run_command", return_value=0) as run:
            run_pr_lane(runner, [], None)
        commands = [c.args[0] for c in run.call_args_list]
        assert not any("pytest" in c for c in commands)

    def test_a_failed_suite_fails_the_lane_and_keeps_the_raw_data(self, manifest):
        runner = TestRunner()
        with patch.object(
            runner,
            "run_command",
            side_effect=lambda cmd: 1 if "--db=POSTGRESQL" in cmd else 0,
        ) as run:
            code = run_pr_lane(runner, manifest.resolve(["postgresql"]), None)
        commands = [c.args[0] for c in run.call_args_list]
        assert code == 1
        assert ["coverage", "combine"] not in commands


class TestPrCategoryCli:
    def invoke(self, *args):
        with patch("protean.cli.test.run_pr_lane", return_value=0) as lane:
            result = CliRunner().invoke(
                app, ["test", "-c", "PR", *args], standalone_mode=False
            )
        assert result.exit_code == 0, result.output
        _, adapters, core_workers = lane.call_args.args
        return [e.name for e in adapters], core_workers

    def test_defaults_to_core_and_the_pr_adapters(self, manifest):
        adapters, workers = self.invoke()
        assert adapters == [e.name for e in manifest.pr_adapters()]
        assert workers == "logical"

    def test_named_adapters(self):
        assert self.invoke("-a", "elasticsearch", "-a", "sqlite")[0] == [
            "elasticsearch",
            "sqlite",
        ]

    def test_no_core(self):
        assert self.invoke("--no-core")[1] is None

    def test_no_adapters(self):
        assert self.invoke("--no-adapters")[0] == []

    def test_no_core_and_no_adapters_is_rejected(self):
        with patch("protean.cli.test.run_pr_lane", return_value=0) as lane:
            result = CliRunner().invoke(
                app, ["test", "-c", "PR", "--no-core", "--no-adapters"]
            )
        assert result.exit_code != 0
        assert "nothing to run" in result.output
        lane.assert_not_called()

    def test_sequential_runs_core_in_one_process(self):
        assert self.invoke("--sequential")[1] == "0"

    def test_workers_are_validated(self):
        with patch("protean.cli.test.run_pr_lane", return_value=0):
            result = CliRunner().invoke(app, ["test", "-c", "PR", "-n", "many"])
        assert result.exit_code != 0

    def test_a_failed_lane_exits_non_zero(self):
        with patch("protean.cli.test.run_pr_lane", return_value=1):
            result = CliRunner().invoke(app, ["test", "-c", "PR"])
        assert result.exit_code == 1


class TestSelectAdaptersCli:
    def test_prints_the_matrix_for_the_changed_files(self, tmp_path: Path):
        changed = tmp_path / "changed.txt"
        changed.write_text(
            "src/protean/adapters/database/elasticsearch.py\n\ndocs/x.md\n"
        )
        with patch("protean.cli.test.TestRunner.run_command") as run:
            result = CliRunner().invoke(app, ["test", "select-adapters", str(changed)])
        assert result.exit_code == 0, result.output
        legs = [leg["leg"] for leg in json.loads(result.output)["include"]]
        assert legs == ["postgresql", "redis", "elasticsearch"]
        # The `test` callback must not run CORE before a subcommand.
        run.assert_not_called()

    def select(self, tmp_path: Path, *files: str) -> dict[str, str]:
        changed = tmp_path / "changed.txt"
        changed.write_text("".join(f"{f}\n" for f in files))
        result = CliRunner().invoke(app, ["test", "select-adapters", str(changed)])
        assert result.exit_code == 0, result.output
        return {
            leg["leg"]: leg["services"] for leg in json.loads(result.output)["include"]
        }

    def test_no_changes_run_the_redis_leg_with_postgres(self, tmp_path: Path):
        assert self.select(tmp_path) == {
            "postgresql": "postgres",
            "redis": "redis postgres",
        }

    def test_a_message_db_test_change_starts_postgres_in_its_leg(self, tmp_path):
        legs = self.select(
            tmp_path, "tests/unit_of_work/test_stale_event_sourced_outbox.py"
        )
        assert list(legs) == ["postgresql", "redis", "sqlite", "message-db"]
        assert legs["message-db"] == "message-db postgres"
