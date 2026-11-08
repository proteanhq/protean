"""Tests for IR compatibility configuration — src/protean/ir/config.py."""

import json
import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.ir.config import (
    CompatConfig,
    _parse_config,
    load_config,
)
from tests.ir.support.git_repo import commit_ir
from tests.shared import change_working_directory_to

pytestmark = pytest.mark.usefixtures("isolated_git")

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(directory: Path, content: str) -> Path:
    """Write *content* as config.toml into *directory* and return the path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.toml"
    path.write_text(content, encoding="utf-8")
    return path


def _write_ir(directory: Path, ir_dict: dict) -> Path:
    """Write *ir_dict* as ir.json into *directory* and return the path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "ir.json"
    path.write_text(json.dumps(ir_dict, indent=2), encoding="utf-8")
    return path


_TEST7_DOMAIN = str(
    Path(__file__).parent.parent / "support" / "domains" / "test7" / "publishing7.py"
)


def _run_compat_hook(monkeypatch, repo: Path, baseline_ir: dict) -> int:
    """Commit *baseline_ir* in a git repository at *repo*, run the compat hook
    against HEAD from inside it, and return the exit code."""
    from protean.cli.hooks import check_compat_hook

    commit_ir(repo, baseline_ir)
    os.chdir(repo)
    monkeypatch.setattr(
        sys,
        "argv",
        ["protean-check-compat", "-d", _TEST7_DOMAIN, "--dir", ".protean"],
    )
    with pytest.raises(SystemExit) as exc_info:
        check_compat_hook()
    return exc_info.value.code


def _live_ir_for_test7() -> dict:
    """Return the live IR dict for the test7 domain (publishing7.py)."""
    from protean.ir.builder import IRBuilder
    from protean.utils.domain_discovery import derive_domain

    domain = derive_domain(_TEST7_DOMAIN)
    domain.init(traverse=False)
    return IRBuilder(domain).build()


# ---------------------------------------------------------------------------
# TestCompatConfigDefaults
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCompatConfigDefaults:
    """CompatConfig has correct default values."""

    def test_defaults(self):
        config = CompatConfig()
        assert config.strictness == "strict"
        assert config.exclude == ()
        assert config.min_versions_before_removal == 3
        assert config.staleness_enabled is True

    def test_frozen(self):
        config = CompatConfig()
        with pytest.raises(Exception):
            config.strictness = "warn"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestCompatConfigValidation
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCompatConfigValidation:
    """CompatConfig validates input values."""

    @pytest.mark.parametrize(
        "field, value",
        [
            ("strictness", "strict"),
            ("strictness", "warn"),
            ("strictness", "off"),
            ("exclude", ("myapp.internal.LegacyEvent",)),
            ("min_versions_before_removal", 5),
        ],
    )
    def test_accepts_a_valid_value(self, field, value):
        config = CompatConfig(**{field: value})
        assert getattr(config, field) == value

    @pytest.mark.parametrize("value", ["invalid", [], {}, 1])
    def test_invalid_strictness_raises_value_error(self, value):
        with pytest.raises(ValueError, match="Invalid strictness value"):
            CompatConfig(strictness=value)

    def test_non_mapping_domains_raises(self):
        with pytest.raises(ValueError, match="domains must be a mapping"):
            CompatConfig(domains=["identity"])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TestIsExcluded
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestIsExcluded:
    """CompatConfig.is_excluded() matches FQNs."""

    @pytest.mark.parametrize(
        "exclude, fqn, expected",
        [
            (("myapp.internal.LegacyEvent",), "myapp.internal.LegacyEvent", True),
            (("myapp.internal.LegacyEvent",), "myapp.models.User", False),
            ((), "anything.Foo", False),
            (("a.B", "c.D"), "a.B", True),
            (("a.B", "c.D"), "c.D", True),
            (("a.B", "c.D"), "e.F", False),
        ],
    )
    def test_matches_only_listed_fqns(self, exclude, fqn, expected):
        assert CompatConfig(exclude=exclude).is_excluded(fqn) is expected


# ---------------------------------------------------------------------------
# TestLoadConfig — file loading
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestLoadConfigDefaults:
    """load_config() returns defaults when no config.toml exists."""

    @pytest.mark.parametrize(
        "make_path",
        [lambda t: t, lambda t: t / "nonexistent", lambda t: str(t)],
        ids=["no file", "directory missing", "str path"],
    )
    def test_returns_defaults(self, tmp_path, make_path):
        assert load_config(make_path(tmp_path)) == CompatConfig()


@pytest.mark.no_test_domain
class TestLoadConfigFromFile:
    """load_config() reads and parses .protean/config.toml."""

    @pytest.mark.parametrize(
        "content, field, expected",
        [
            (
                '[compatibility]\nexclude = ["myapp.Legacy", "myapp.Old"]\n',
                "exclude",
                ("myapp.Legacy", "myapp.Old"),
            ),
            (
                "[compatibility.deprecation]\nmin_versions_before_removal = 5\n",
                "min_versions_before_removal",
                5,
            ),
            ("[staleness]\nenabled = false\n", "staleness_enabled", False),
        ],
        ids=["exclude", "min_versions", "staleness"],
    )
    def test_reads_a_setting(self, tmp_path, content, field, expected):
        _write_config(tmp_path, content)
        assert getattr(load_config(tmp_path), field) == expected

    def test_reads_full_config(self, tmp_path):
        _write_config(
            tmp_path,
            """\
[compatibility]
strictness = "off"
exclude = ["myapp.internal.LegacyEvent"]

[compatibility.deprecation]
min_versions_before_removal = 2

[staleness]
enabled = false
""",
        )
        config = load_config(tmp_path)
        assert config.strictness == "off"
        assert config.exclude == ("myapp.internal.LegacyEvent",)
        assert config.min_versions_before_removal == 2
        assert config.staleness_enabled is False

    def test_empty_config_file_returns_defaults(self, tmp_path):
        _write_config(tmp_path, "")
        config = load_config(tmp_path)
        assert config == CompatConfig()

    def test_partial_config_merges_with_defaults(self, tmp_path):
        _write_config(tmp_path, '[compatibility]\nstrictness = "warn"\n')
        config = load_config(tmp_path)
        assert config.strictness == "warn"
        assert config.exclude == ()  # default
        assert config.staleness_enabled is True  # default


# ---------------------------------------------------------------------------
# TestLoadConfigErrors
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestLoadConfigErrors:
    """load_config() raises on invalid files."""

    @pytest.mark.parametrize(
        "content, message",
        [
            ("{ not valid toml }", "Invalid TOML"),
            ('[compatibility]\nstrictness = "invalid"\n', "Invalid strictness value"),
            ('[compatibility]\nexclude = "not a list"\n', "must be a list of strings"),
            ("[compatibility]\nexclude = [1, 2, 3]\n", "must be a list of strings"),
            (
                '[compatibility.deprecation]\nmin_versions_before_removal = "x"\n',
                "positive integer",
            ),
            (
                "[compatibility.deprecation]\nmin_versions_before_removal = 0\n",
                "positive integer",
            ),
            (
                "[compatibility.deprecation]\nmin_versions_before_removal = -1\n",
                "positive integer",
            ),
            ('[staleness]\nenabled = "yes"\n', "must be a boolean"),
            ('domains = ["identity"]\n', "domains must be a TOML table"),
            ("[domains]\nidentity = 3\n", "domains entries must be string"),
        ],
        ids=[
            "invalid toml",
            "invalid strictness",
            "non-list exclude",
            "non-string exclude items",
            "non-int min_versions",
            "zero min_versions",
            "negative min_versions",
            "non-bool staleness",
            "non-table domains",
            "non-string domains entry",
        ],
    )
    def test_raises_on_an_invalid_value(self, tmp_path, content, message):
        _write_config(tmp_path, content)
        with pytest.raises(ValueError, match=message):
            load_config(tmp_path)

    def test_raises_on_unreadable_file(self, tmp_path):
        """config.toml is a directory — should raise ValueError."""
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "config.toml").mkdir()
        with pytest.raises(ValueError, match="Could not read"):
            load_config(tmp_path)


# ---------------------------------------------------------------------------
# TestParseConfig — _parse_config unit tests
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestParseConfig:
    """Direct _parse_config() tests for edge cases."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ({}, CompatConfig()),
            ({"unknown_section": {"key": "value"}}, CompatConfig()),
            (
                {"compatibility": {"strictness": "warn"}},
                CompatConfig(strictness="warn"),
            ),
            ({"staleness": {"enabled": False}}, CompatConfig(staleness_enabled=False)),
        ],
        ids=[
            "empty",
            "unknown keys ignored",
            "compatibility without deprecation",
            "staleness without compatibility",
        ],
    )
    def test_fills_missing_settings_with_defaults(self, raw, expected):
        assert _parse_config(raw) == expected


# ---------------------------------------------------------------------------
# TestStalenessWithConfig — staleness check respects config
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestStalenessWithConfig:
    """check_staleness() respects config.staleness_enabled."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_returns_fresh_when_staleness_disabled(self):
        from protean.ir.staleness import StalenessStatus, check_staleness

        config = CompatConfig(staleness_enabled=False)
        result = check_staleness("publishing7.py", self._protean_dir, config=config)
        assert result.status == StalenessStatus.FRESH
        assert result.domain_checksum is None
        assert result.stored_checksum is None

    def test_staleness_enabled_by_default(self):
        from protean.ir.staleness import StalenessStatus, check_staleness

        # No config file, no ir.json → NO_IR
        result = check_staleness("publishing7.py", self._protean_dir)
        assert result.status == StalenessStatus.NO_IR

    def test_config_loaded_from_file_when_not_provided(self):
        from protean.ir.staleness import StalenessStatus, check_staleness

        # Write config that disables staleness
        _write_config(self._protean_dir, "[staleness]\nenabled = false\n")
        result = check_staleness("publishing7.py", self._protean_dir)
        assert result.status == StalenessStatus.FRESH


# ---------------------------------------------------------------------------
# TestDiffCLIWithConfig — diff CLI respects config
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDiffCLIWithConfig:
    """protean ir diff respects .protean/config.toml."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_diff_exits_0_when_strictness_off(self):
        # The baseline lacks a field the live domain has: a change exists, and
        # strictness=off must still exit 0 and print no diff.
        baseline_ir = json.loads(json.dumps(_live_ir_for_test7()))
        baseline_ir["checksum"] = "sha256:modified_baseline_off"
        for cluster in baseline_ir.get("clusters", {}).values():
            cluster["aggregate"]["fields"]["extra_required_field"] = {
                "type": "String",
                "required": True,
                "unique": False,
                "identifier": False,
            }
            break
        _write_config(self._protean_dir, '[compatibility]\nstrictness = "off"\n')
        _write_ir(self._protean_dir, baseline_ir)

        result = runner.invoke(
            app,
            [
                "ir",
                "diff",
                "--domain",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        )
        assert result.exit_code == 0, result.output
        assert result.stdout.strip() == (
            "Compatibility checking is disabled (strictness=off)."
        )

    def test_diff_warn_mode_exits_0_on_breaking(self):
        """With strictness=warn, breaking changes print warning but exit 0."""
        live_ir = _live_ir_for_test7()

        # Create baseline with an extra field
        baseline_ir = json.loads(json.dumps(live_ir))
        baseline_ir["checksum"] = "sha256:modified_baseline"
        for cluster in baseline_ir.get("clusters", {}).values():
            cluster["aggregate"]["fields"]["extra_required_field"] = {
                "type": "String",
                "required": True,
                "unique": False,
                "identifier": False,
            }
            break

        _write_config(self._protean_dir, '[compatibility]\nstrictness = "warn"\n')
        _write_ir(self._protean_dir, baseline_ir)

        result = runner.invoke(
            app,
            [
                "ir",
                "diff",
                "--domain",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        )
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# TestCheckCLIWithConfig — `protean ir check` respects config
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckCLIWithConfig:
    """protean ir check respects .protean/config.toml."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_check_exits_0_when_staleness_disabled(self):
        _write_config(self._protean_dir, "[staleness]\nenabled = false\n")

        result = runner.invoke(
            app,
            [
                "ir",
                "check",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        )
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# TestHooksWithConfig — hooks respect config
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCompatHookWithConfig:
    """check_compat_hook() respects .protean/config.toml."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_exits_0_when_strictness_off(self, monkeypatch):
        from protean.cli.hooks import check_compat_hook

        _write_config(self._protean_dir, '[compatibility]\nstrictness = "off"\n')

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "protean-check-compat",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            check_compat_hook()
        assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# TestModuleExports — config types exported from protean.ir
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestModuleExports:
    """CompatConfig and load_config are accessible via protean.ir."""

    def test_compat_config_importable(self):
        from protean.ir import CompatConfig as C

        assert C is CompatConfig

    def test_load_config_importable(self):
        from protean.ir import load_config as lc

        assert lc is load_config

    def test_compat_config_in_all(self):
        import protean.ir

        assert "CompatConfig" in protean.ir.__all__

    def test_load_config_in_all(self):
        import protean.ir

        assert "load_config" in protean.ir.__all__


# ---------------------------------------------------------------------------
# TestCompatConfigPostInitValidation — __post_init__ validates all fields
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCompatConfigPostInitValidation:
    """CompatConfig.__post_init__ validates all fields."""

    @pytest.mark.parametrize("value", [0, -1])
    def test_rejects_non_positive_min_versions_direct(self, value):
        with pytest.raises(ValueError, match="positive integer"):
            CompatConfig(min_versions_before_removal=value)

    def test_rejects_non_bool_staleness_direct(self):
        with pytest.raises(ValueError, match="boolean"):
            CompatConfig(staleness_enabled="yes")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TestParseConfigSectionTypeChecks — non-table sections raise ValueError
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestParseConfigSectionTypeChecks:
    """_parse_config() rejects non-table sections."""

    def test_compatibility_not_a_table(self):
        with pytest.raises(ValueError, match="compatibility must be a TOML table"):
            _parse_config({"compatibility": "strict"})

    def test_staleness_not_a_table(self):
        with pytest.raises(ValueError, match="staleness must be a TOML table"):
            _parse_config({"staleness": True})

    def test_deprecation_not_a_table(self):
        with pytest.raises(
            ValueError, match="compatibility.deprecation must be a TOML table"
        ):
            _parse_config({"compatibility": {"deprecation": "fast"}})

    def test_domains_not_a_table(self):
        with pytest.raises(ValueError) as exc_info:
            _parse_config({"domains": ["identity"]})
        assert str(exc_info.value) == "domains must be a TOML table, not list"

    def test_domains_entry_not_a_string(self):
        with pytest.raises(ValueError) as exc_info:
            _parse_config({"domains": {"identity": 3}})
        assert str(exc_info.value) == (
            'domains entries must be string key-value pairs (name = "module.path")'
        )

    def test_domains_table_maps_names_to_module_paths(self):
        config = _parse_config({"domains": {"identity": "identity.domain"}})
        assert config.domains == {"identity": "identity.domain"}


# ---------------------------------------------------------------------------
# TestLoadConfigErrorHandling — CLI/hooks handle config errors gracefully
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckCLIConfigError:
    """protean ir check handles invalid config gracefully."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_check_exits_2_on_invalid_config(self):
        _write_config(self._protean_dir, "{ invalid toml }")
        result = runner.invoke(
            app,
            [
                "ir",
                "check",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        )
        assert result.exit_code == 2


@pytest.mark.no_test_domain
class TestStalenessHookConfigError:
    """check_staleness_hook handles invalid config gracefully."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_exits_1_on_invalid_config(self, capsys, monkeypatch):
        from protean.cli.hooks import check_staleness_hook

        _write_config(self._protean_dir, "{ invalid toml }")

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "protean-check-staleness",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            check_staleness_hook()
        assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "config.toml" in captured.err.lower()


# ---------------------------------------------------------------------------
# TestCompatHookConfigError — compat hook handles invalid config
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCompatHookConfigError:
    """check_compat_hook handles invalid config gracefully."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_exits_1_on_invalid_config(self, capsys, monkeypatch):
        from protean.cli.hooks import check_compat_hook

        _write_config(self._protean_dir, "{ invalid toml }")

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "protean-check-compat",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            check_compat_hook()
        assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "config.toml" in captured.err.lower()


# ---------------------------------------------------------------------------
# TestCompatHookContractBreaking — has_breaking_changes path in compat hook
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCompatHookContractBreaking:
    """check_compat_hook() handles contract-level breaking changes."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_exits_1_on_contract_breaking_changes(self, capsys, monkeypatch):
        """Removed published event -> has_breaking_changes=True -> exit 1."""
        live_ir = _live_ir_for_test7()

        # Create baseline with an extra published event
        baseline_ir = json.loads(json.dumps(live_ir))
        baseline_ir["checksum"] = "sha256:hook_contract_breaking"
        baseline_events = baseline_ir.get("contracts", {}).get("events", [])
        baseline_events.append(
            {
                "fqn": "tests.fake.HookRemovedEvent",
                "type": "Tests.Fake.HookRemovedEvent.v1",
                "version": "v1",
                "fields": {"data": {"type": "String", "required": True}},
            }
        )
        baseline_ir.setdefault("contracts", {})["events"] = baseline_events

        code = _run_compat_hook(monkeypatch, self._protean_dir.parent, baseline_ir)
        assert code == 1
        err = capsys.readouterr().err
        assert "Breaking IR changes detected" in err
        assert "HookRemovedEvent" in err

    def test_exits_0_on_contract_breaking_warn_mode(self, monkeypatch):
        """Contract breaking + strictness=warn -> exit 0."""
        live_ir = _live_ir_for_test7()

        baseline_ir = json.loads(json.dumps(live_ir))
        baseline_ir["checksum"] = "sha256:hook_contract_warn"
        baseline_events = baseline_ir.get("contracts", {}).get("events", [])
        baseline_events.append(
            {
                "fqn": "tests.fake.HookRemovedEventWarn",
                "type": "Tests.Fake.HookRemovedEventWarn.v1",
                "version": "v1",
                "fields": {"data": {"type": "String", "required": True}},
            }
        )
        baseline_ir.setdefault("contracts", {})["events"] = baseline_events

        _write_config(self._protean_dir, '[compatibility]\nstrictness = "warn"\n')

        code = _run_compat_hook(monkeypatch, self._protean_dir.parent, baseline_ir)
        assert code == 0


# ---------------------------------------------------------------------------
# TestCompatHookWarnMode — warn strictness in compat hook
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCompatHookWarnMode:
    """check_compat_hook() with strictness=warn prints but exits 0."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_exits_0_with_breaking_changes_in_warn_mode(self, capsys, monkeypatch):
        live_ir = _live_ir_for_test7()

        # Create baseline with an extra required field
        baseline_ir = json.loads(json.dumps(live_ir))
        baseline_ir["checksum"] = "sha256:modified_baseline"
        for cluster in baseline_ir.get("clusters", {}).values():
            cluster["aggregate"]["fields"]["extra_required_field"] = {
                "type": "String",
                "required": True,
                "unique": False,
                "identifier": False,
            }
            break

        _write_config(self._protean_dir, '[compatibility]\nstrictness = "warn"\n')

        code = _run_compat_hook(monkeypatch, self._protean_dir.parent, baseline_ir)
        assert code == 0

        captured = capsys.readouterr()
        assert "breaking" in captured.err.lower()
        assert "warn" in captured.err.lower()


# ---------------------------------------------------------------------------
# TestCompatHookExclude — exclude filter in compat hook
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCompatHookExclude:
    """check_compat_hook() filters excluded elements."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_excluded_elements_not_counted_as_breaking(self, monkeypatch):
        live_ir = _live_ir_for_test7()

        # Create baseline with an extra required field on the first aggregate
        baseline_ir = json.loads(json.dumps(live_ir))
        baseline_ir["checksum"] = "sha256:modified_baseline"
        target_fqn = None
        for cluster_fqn, cluster in baseline_ir.get("clusters", {}).items():
            target_fqn = cluster_fqn
            cluster["aggregate"]["fields"]["extra_required_field"] = {
                "type": "String",
                "required": True,
                "unique": False,
                "identifier": False,
            }
            break

        # Exclude the aggregate that has the breaking change
        _write_config(
            self._protean_dir,
            f'[compatibility]\nexclude = ["{target_fqn}"]\n',
        )

        code = _run_compat_hook(monkeypatch, self._protean_dir.parent, baseline_ir)
        assert code == 0


# ---------------------------------------------------------------------------
# TestDiffCLIExcludeFilter — exclude filter in diff CLI
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDiffCLIExcludeFilter:
    """protean ir diff filters excluded elements from the report."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_excluded_breaking_change_exits_3_not_1(self):
        """With exclude, breaking changes are filtered; exits 3 (non-breaking)."""
        live_ir = _live_ir_for_test7()

        # Create baseline with an extra required field
        baseline_ir = json.loads(json.dumps(live_ir))
        baseline_ir["checksum"] = "sha256:modified_baseline"
        target_fqn = None
        for cluster_fqn, cluster in baseline_ir.get("clusters", {}).items():
            target_fqn = cluster_fqn
            cluster["aggregate"]["fields"]["extra_required_field"] = {
                "type": "String",
                "required": True,
                "unique": False,
                "identifier": False,
            }
            break

        _write_config(
            self._protean_dir,
            f'[compatibility]\nexclude = ["{target_fqn}"]\n',
        )
        _write_ir(self._protean_dir, baseline_ir)

        result = runner.invoke(
            app,
            [
                "ir",
                "diff",
                "--domain",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        )
        # Breaking change was excluded, so exit code should be 3 (non-breaking)
        assert result.exit_code == 3


# ---------------------------------------------------------------------------
# TestDiffCLIContractBreaking — summary.has_breaking_changes path
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDiffCLIContractBreaking:
    """protean ir diff handles contract-level breaking changes."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_contract_breaking_exits_1(self):
        """Removed published event triggers summary.has_breaking_changes."""
        live_ir = _live_ir_for_test7()

        # Create baseline with an extra published event contract
        baseline_ir = json.loads(json.dumps(live_ir))
        baseline_ir["checksum"] = "sha256:modified_baseline_contracts"
        baseline_events = baseline_ir.get("contracts", {}).get("events", [])
        baseline_events.append(
            {
                "fqn": "tests.fake.RemovedEvent",
                "type": "Tests.Fake.RemovedEvent.v1",
                "version": "v1",
                "fields": {"data": {"type": "String", "required": True}},
            }
        )
        baseline_ir.setdefault("contracts", {})["events"] = baseline_events

        _write_ir(self._protean_dir, baseline_ir)

        result = runner.invoke(
            app,
            [
                "ir",
                "diff",
                "--domain",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        )
        assert result.exit_code == 1

    def test_contract_breaking_warn_exits_0(self):
        """With strictness=warn, contract breaking changes exit 0."""
        live_ir = _live_ir_for_test7()

        baseline_ir = json.loads(json.dumps(live_ir))
        baseline_ir["checksum"] = "sha256:modified_baseline_contracts_warn"
        baseline_events = baseline_ir.get("contracts", {}).get("events", [])
        baseline_events.append(
            {
                "fqn": "tests.fake.RemovedEvent2",
                "type": "Tests.Fake.RemovedEvent2.v1",
                "version": "v1",
                "fields": {"data": {"type": "String", "required": True}},
            }
        )
        baseline_ir.setdefault("contracts", {})["events"] = baseline_events

        _write_config(self._protean_dir, '[compatibility]\nstrictness = "warn"\n')
        _write_ir(self._protean_dir, baseline_ir)

        result = runner.invoke(
            app,
            [
                "ir",
                "diff",
                "--domain",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        )
        assert result.exit_code == 0
