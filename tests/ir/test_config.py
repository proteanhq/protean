"""Tests for IR compatibility configuration — src/protean/ir/config.py."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.ir.config import (
    CompatConfig,
    _parse_config,
    load_config,
)
from tests.shared import change_working_directory_to

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


def _live_ir_for_test7() -> dict:
    """Return the live IR dict for the test7 domain (publishing7.py)."""
    from protean.ir.builder import IRBuilder
    from protean.utils.domain_discovery import derive_domain

    domain = derive_domain("publishing7.py")
    domain.init(traverse=False)
    return IRBuilder(domain).build()


# ---------------------------------------------------------------------------
# TestCompatConfigDefaults
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCompatConfigDefaults:
    """CompatConfig has correct default values."""

    def test_default_strictness(self):
        config = CompatConfig()
        assert config.strictness == "strict"

    def test_default_exclude(self):
        config = CompatConfig()
        assert config.exclude == ()

    def test_default_min_versions(self):
        config = CompatConfig()
        assert config.min_versions_before_removal == 3

    def test_default_staleness_enabled(self):
        config = CompatConfig()
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

    def test_valid_strictness_strict(self):
        config = CompatConfig(strictness="strict")
        assert config.strictness == "strict"

    def test_valid_strictness_warn(self):
        config = CompatConfig(strictness="warn")
        assert config.strictness == "warn"

    def test_valid_strictness_off(self):
        config = CompatConfig(strictness="off")
        assert config.strictness == "off"

    def test_invalid_strictness_raises(self):
        with pytest.raises(ValueError, match="Invalid strictness value"):
            CompatConfig(strictness="invalid")

    def test_custom_exclude(self):
        config = CompatConfig(exclude=("myapp.internal.LegacyEvent",))
        assert config.exclude == ("myapp.internal.LegacyEvent",)

    def test_custom_min_versions(self):
        config = CompatConfig(min_versions_before_removal=5)
        assert config.min_versions_before_removal == 5


# ---------------------------------------------------------------------------
# TestIsExcluded
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestIsExcluded:
    """CompatConfig.is_excluded() matches FQNs."""

    def test_excludes_matching_fqn(self):
        config = CompatConfig(exclude=("myapp.internal.LegacyEvent",))
        assert config.is_excluded("myapp.internal.LegacyEvent") is True

    def test_does_not_exclude_non_matching(self):
        config = CompatConfig(exclude=("myapp.internal.LegacyEvent",))
        assert config.is_excluded("myapp.models.User") is False

    def test_empty_exclude_matches_nothing(self):
        config = CompatConfig(exclude=())
        assert config.is_excluded("anything.Foo") is False

    def test_multiple_excludes(self):
        config = CompatConfig(exclude=("a.B", "c.D"))
        assert config.is_excluded("a.B") is True
        assert config.is_excluded("c.D") is True
        assert config.is_excluded("e.F") is False


# ---------------------------------------------------------------------------
# TestLoadConfig — file loading
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestLoadConfigDefaults:
    """load_config() returns defaults when no config.toml exists."""

    def test_returns_defaults_when_no_file(self, tmp_path):
        config = load_config(tmp_path)
        assert config == CompatConfig()

    def test_returns_defaults_when_directory_missing(self, tmp_path):
        config = load_config(tmp_path / "nonexistent")
        assert config == CompatConfig()

    def test_accepts_str_path(self, tmp_path):
        config = load_config(str(tmp_path))
        assert config == CompatConfig()


@pytest.mark.no_test_domain
class TestLoadConfigFromFile:
    """load_config() reads and parses .protean/config.toml."""

    def test_reads_strictness(self, tmp_path):
        _write_config(tmp_path, '[compatibility]\nstrictness = "warn"\n')
        config = load_config(tmp_path)
        assert config.strictness == "warn"

    def test_reads_exclude(self, tmp_path):
        _write_config(
            tmp_path,
            '[compatibility]\nexclude = ["myapp.Legacy", "myapp.Old"]\n',
        )
        config = load_config(tmp_path)
        assert config.exclude == ("myapp.Legacy", "myapp.Old")

    def test_reads_deprecation_min_versions(self, tmp_path):
        _write_config(
            tmp_path,
            "[compatibility.deprecation]\nmin_versions_before_removal = 5\n",
        )
        config = load_config(tmp_path)
        assert config.min_versions_before_removal == 5

    def test_reads_staleness_enabled(self, tmp_path):
        _write_config(tmp_path, "[staleness]\nenabled = false\n")
        config = load_config(tmp_path)
        assert config.staleness_enabled is False

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

    def test_raises_on_invalid_toml(self, tmp_path):
        _write_config(tmp_path, "{ not valid toml }")
        with pytest.raises(ValueError, match="Invalid TOML"):
            load_config(tmp_path)

    def test_raises_on_invalid_strictness(self, tmp_path):
        _write_config(tmp_path, '[compatibility]\nstrictness = "invalid"\n')
        with pytest.raises(ValueError, match="Invalid strictness value"):
            load_config(tmp_path)

    def test_raises_on_non_list_exclude(self, tmp_path):
        _write_config(tmp_path, '[compatibility]\nexclude = "not a list"\n')
        with pytest.raises(ValueError, match="must be a list of strings"):
            load_config(tmp_path)

    def test_raises_on_non_string_exclude_items(self, tmp_path):
        _write_config(tmp_path, "[compatibility]\nexclude = [1, 2, 3]\n")
        with pytest.raises(ValueError, match="must be a list of strings"):
            load_config(tmp_path)

    def test_raises_on_non_int_min_versions(self, tmp_path):
        _write_config(
            tmp_path,
            '[compatibility.deprecation]\nmin_versions_before_removal = "x"\n',
        )
        with pytest.raises(ValueError, match="positive integer"):
            load_config(tmp_path)

    def test_raises_on_zero_min_versions(self, tmp_path):
        _write_config(
            tmp_path,
            "[compatibility.deprecation]\nmin_versions_before_removal = 0\n",
        )
        with pytest.raises(ValueError, match="positive integer"):
            load_config(tmp_path)

    def test_raises_on_negative_min_versions(self, tmp_path):
        _write_config(
            tmp_path,
            "[compatibility.deprecation]\nmin_versions_before_removal = -1\n",
        )
        with pytest.raises(ValueError, match="positive integer"):
            load_config(tmp_path)

    def test_raises_on_non_bool_staleness(self, tmp_path):
        _write_config(tmp_path, '[staleness]\nenabled = "yes"\n')
        with pytest.raises(ValueError, match="must be a boolean"):
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

    def test_empty_dict(self):
        config = _parse_config({})
        assert config == CompatConfig()

    def test_unknown_keys_ignored(self):
        config = _parse_config({"unknown_section": {"key": "value"}})
        assert config == CompatConfig()

    def test_compatibility_without_deprecation(self):
        config = _parse_config({"compatibility": {"strictness": "warn"}})
        assert config.strictness == "warn"
        assert config.min_versions_before_removal == 3  # default

    def test_staleness_without_compatibility(self):
        config = _parse_config({"staleness": {"enabled": False}})
        assert config.staleness_enabled is False
        assert config.strictness == "strict"  # default


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
        result = check_staleness(
            "publishing7.py", self._protean_dir, config=config
        )
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
        _write_config(self._protean_dir, '[compatibility]\nstrictness = "off"\n')

        # Even without valid IR files, strictness=off should exit 0
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
        assert "disabled" in result.output.lower()

    def test_diff_warn_mode_exits_0_on_breaking(self):
        """With strictness=warn, breaking changes print warning but exit 0."""
        live_ir = _live_ir_for_test7()

        # Create baseline with an extra field
        baseline_ir = json.loads(json.dumps(live_ir))
        baseline_ir["checksum"] = "sha256:modified_baseline"
        for cluster_fqn, cluster in baseline_ir.get("clusters", {}).items():
            cluster["aggregate"]["fields"]["extra_required_field"] = {
                "type": "String",
                "required": True,
                "unique": False,
                "identifier": False,
            }
            break

        _write_config(
            self._protean_dir, '[compatibility]\nstrictness = "warn"\n'
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
class TestStalenessHookWithConfig:
    """check_staleness_hook() respects .protean/config.toml."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_exits_0_when_staleness_disabled(self):
        from protean.cli.hooks import check_staleness_hook

        _write_config(self._protean_dir, "[staleness]\nenabled = false\n")

        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 0


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

    def test_exits_0_when_strictness_off(self):
        from protean.cli.hooks import check_compat_hook

        _write_config(
            self._protean_dir, '[compatibility]\nstrictness = "off"\n'
        )

        with patch(
            "sys.argv",
            [
                "protean-check-compat",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
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

    def test_rejects_zero_min_versions_direct(self):
        with pytest.raises(ValueError, match="positive integer"):
            CompatConfig(min_versions_before_removal=0)

    def test_rejects_negative_min_versions_direct(self):
        with pytest.raises(ValueError, match="positive integer"):
            CompatConfig(min_versions_before_removal=-1)

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
        with pytest.raises(ValueError, match="compatibility.deprecation must be a TOML table"):
            _parse_config({"compatibility": {"deprecation": "fast"}})


# ---------------------------------------------------------------------------
# TestLoadConfigErrorHandling — CLI/hooks handle config errors gracefully
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDiffCLIConfigError:
    """protean ir diff handles invalid config gracefully."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_diff_aborts_on_invalid_config(self):
        _write_config(self._protean_dir, "{ invalid toml }")
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
        assert result.exit_code != 0


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

    def test_exits_1_on_invalid_config(self, capsys):
        from protean.cli.hooks import check_staleness_hook

        _write_config(self._protean_dir, "{ invalid toml }")

        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
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

    def test_exits_1_on_invalid_config(self, capsys):
        from protean.cli.hooks import check_compat_hook

        _write_config(self._protean_dir, "{ invalid toml }")

        with patch(
            "sys.argv",
            [
                "protean-check-compat",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
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

    def test_exits_1_on_contract_breaking_changes(self):
        """Removed published event -> has_breaking_changes=True -> exit 1."""
        from protean.cli.hooks import check_compat_hook

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

        with patch(
            "protean.ir.git.load_ir_from_commit", return_value=baseline_ir
        ):
            with patch(
                "sys.argv",
                [
                    "protean-check-compat",
                    "-d",
                    "publishing7.py",
                    "--dir",
                    str(self._protean_dir),
                ],
            ):
                with pytest.raises(SystemExit) as exc_info:
                    check_compat_hook()
                assert exc_info.value.code == 1

    def test_exits_0_on_contract_breaking_warn_mode(self):
        """Contract breaking + strictness=warn -> exit 0."""
        from protean.cli.hooks import check_compat_hook

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

        _write_config(
            self._protean_dir, '[compatibility]\nstrictness = "warn"\n'
        )

        with patch(
            "protean.ir.git.load_ir_from_commit", return_value=baseline_ir
        ):
            with patch(
                "sys.argv",
                [
                    "protean-check-compat",
                    "-d",
                    "publishing7.py",
                    "--dir",
                    str(self._protean_dir),
                ],
            ):
                with pytest.raises(SystemExit) as exc_info:
                    check_compat_hook()
                assert exc_info.value.code == 0


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

    def test_exits_0_with_breaking_changes_in_warn_mode(self, capsys):
        from protean.cli.hooks import check_compat_hook

        live_ir = _live_ir_for_test7()

        # Create baseline with an extra required field
        baseline_ir = json.loads(json.dumps(live_ir))
        baseline_ir["checksum"] = "sha256:modified_baseline"
        for cluster_fqn, cluster in baseline_ir.get("clusters", {}).items():
            cluster["aggregate"]["fields"]["extra_required_field"] = {
                "type": "String",
                "required": True,
                "unique": False,
                "identifier": False,
            }
            break

        _write_config(
            self._protean_dir, '[compatibility]\nstrictness = "warn"\n'
        )

        with patch(
            "protean.ir.git.load_ir_from_commit", return_value=baseline_ir
        ):
            with patch(
                "sys.argv",
                [
                    "protean-check-compat",
                    "-d",
                    "publishing7.py",
                    "--dir",
                    str(self._protean_dir),
                ],
            ):
                with pytest.raises(SystemExit) as exc_info:
                    check_compat_hook()
                assert exc_info.value.code == 0

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

    def test_excluded_elements_not_counted_as_breaking(self):
        from protean.cli.hooks import check_compat_hook

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

        with patch(
            "protean.ir.git.load_ir_from_commit", return_value=baseline_ir
        ):
            with patch(
                "sys.argv",
                [
                    "protean-check-compat",
                    "-d",
                    "publishing7.py",
                    "--dir",
                    str(self._protean_dir),
                ],
            ):
                with pytest.raises(SystemExit) as exc_info:
                    check_compat_hook()
                # Should exit 0 since the only breaking element is excluded
                assert exc_info.value.code == 0


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

    def test_excluded_breaking_change_exits_2_not_1(self):
        """With exclude, breaking changes are filtered; exits 2 (non-breaking)."""
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
        # Breaking change was excluded, so exit code should be 2 (non-breaking)
        assert result.exit_code == 2


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

        _write_config(
            self._protean_dir, '[compatibility]\nstrictness = "warn"\n'
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
        assert result.exit_code == 0
