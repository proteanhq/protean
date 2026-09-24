"""The adapter manifest (tests/adapters.toml) and the PR lane that reads it.

The first class is the guard: it fails when an adapter module is in no manifest
entry, or when an entry names a path, service or suite that does not exist, so
the PR lane cannot silently stop testing an adapter.
"""

import json
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from protean.cli import app
from protean.cli.test import (
    ADAPTER_LANES,
    ADAPTER_MANIFEST,
    REPO_ROOT,
    TEST_CONFIGS,
    AdapterEntry,
    AdapterManifest,
    TestRunner,
    build_adapter_matrix,
    build_adapter_suites,
    load_adapter_manifest,
    run_pr_lane,
)

# The manifest and the PR lane are file and CLI work; none of it loads a domain.
pytestmark = pytest.mark.no_test_domain

ADAPTERS_SRC = REPO_ROOT / "src" / "protean" / "adapters"
TEST_SUITE_ACTION = REPO_ROOT / ".github" / "actions" / "test-suite" / "action.yml"


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
        "brokers": [],
        "stores": [],
    }
    fields.update(kwargs)
    return AdapterEntry(name=name, lane=lane, **fields)


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

    def test_every_path_exists(self, manifest):
        paths = [p for e in manifest.adapters for p in e.paths] + manifest.trigger_all
        missing = [p for p in paths if not (REPO_ROOT / p).exists()]
        assert not missing, f"{ADAPTER_MANIFEST.name} names missing paths: {missing}"

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
            assert set(entry.brokers) <= set(TEST_CONFIGS["brokers"])
            assert set(entry.stores) <= set(TEST_CONFIGS["eventstores"])

    def test_every_runnable_adapter_runs_something(self, manifest):
        for entry in manifest.adapters:
            if entry.lane in ("pr", "touched"):
                assert entry.markers or entry.databases or entry.brokers or entry.stores

    def test_the_pr_lane_is_postgres_and_redis(self, manifest):
        assert {e.leg for e in manifest.pr_adapters()} == {"postgresql", "redis"}


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

    def test_the_real_manifest_runs_every_dialect_on_a_sqlalchemy_change(
        self, manifest
    ):
        legs = {
            e.leg
            for e in manifest.select(["src/protean/adapters/repository/sqlalchemy.py"])
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

    # Explicit ids: a test id containing "sendgrid" would pick up the root
    # conftest's `--sendgrid` skip.
    @pytest.mark.parametrize(
        "name", ["nope", "memory", "sendgrid"], ids=["unknown", "core", "off"]
    )
    def test_an_unknown_core_or_off_name_is_rejected(self, manifest, name):
        with pytest.raises(typer.BadParameter, match="is not an adapter or leg"):
            manifest.resolve([name])


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
            "Broker: REDIS",
            "Broker: REDIS_PUBSUB",
        ]

    def test_suites_are_coverage_wrapped_and_select_their_tests(self):
        runner = TestRunner()
        entry = _entry(
            "x",
            markers=["postgresql"],
            databases=["POSTGRESQL"],
            brokers=["REDIS"],
            stores=["MESSAGE_DB"],
        )
        by_name = {s.name: s.command for s in build_adapter_suites(runner, [entry])}

        marker = by_name["Marker: postgresql"]
        assert marker[:4] == ["coverage", "run", "--parallel-mode", "-m"]
        assert marker[-3:] == ["postgresql", "--postgresql", "tests"]

        database = by_name["Database: POSTGRESQL"]
        assert database[-1] == "--db=POSTGRESQL"
        assert runner.get_database_marker_expression("POSTGRESQL") in database

        broker = by_name["Broker: REDIS"]
        assert broker[-1] == "--broker=REDIS"

        store = by_name["Event Store: MESSAGE_DB"]
        assert store[-3:] == ["-m", "eventstore", "--store=MESSAGE_DB"]


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
            "src/protean/adapters/repository/elasticsearch.py\n\ndocs/x.md\n"
        )
        with patch("protean.cli.test.TestRunner.run_command") as run:
            result = CliRunner().invoke(app, ["test", "select-adapters", str(changed)])
        assert result.exit_code == 0, result.output
        legs = [leg["leg"] for leg in json.loads(result.output)["include"]]
        assert legs == ["postgresql", "redis", "elasticsearch"]
        # The `test` callback must not run CORE before a subcommand.
        run.assert_not_called()
