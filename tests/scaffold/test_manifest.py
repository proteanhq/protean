"""Tests for the derived project manifest (``.protean/project.json``).

These build a tiny ADR-0030 project tree on disk in ``tmp_path`` and exercise
the manifest module directly. They are filesystem-only and fast: ``domain.py``
holds just enough to parse ``Domain(name=...)``, with no domain boot.
"""

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.scaffold.manifest import (
    MANIFEST_VERSION,
    ManifestDriftStatus,
    ProjectLayout,
    ProjectManifest,
    _derive_domain_name,
    check_manifest_drift,
    load_stored_manifest,
    reconcile_manifest,
    write_manifest,
)
from tests.shared import isolated_filesystem

runner = CliRunner()

DOMAIN_PY_TEMPLATE = '''"""Domain composition root."""

from protean.domain import Domain

{package} = Domain(name="{domain}")
'''


def _make_project(
    root: Path,
    *,
    package: str = "myproj",
    domain: str = "myproj",
    domain_py: str | None = None,
) -> Path:
    """Create a minimal ADR-0030 project tree under *root* and return it."""
    package_dir = root / "src" / package
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "domain.py").write_text(
        domain_py
        if domain_py is not None
        else DOMAIN_PY_TEMPLATE.format(package=package, domain=domain),
        encoding="utf-8",
    )
    (package_dir / "domain.toml").write_text("debug = true\n", encoding="utf-8")
    (root / "tests").mkdir()
    return root


# --------------------------------------------------------------------------- #
# reconcile_manifest — recompute from disk                                     #
# --------------------------------------------------------------------------- #


def test_reconcile_derives_every_field_from_disk(tmp_path: Path) -> None:
    _make_project(tmp_path, package="shopfront", domain="Shopfront")

    manifest = reconcile_manifest(tmp_path)

    assert manifest.manifest_version == MANIFEST_VERSION
    assert manifest.package_name == "shopfront"
    assert manifest.domain_name == "Shopfront"
    assert manifest.layout.composition_root == "src/shopfront/domain.py"
    assert manifest.layout.config_file == "src/shopfront/domain.toml"
    assert manifest.layout.tests_dir == "tests"


def test_reconcile_layout_paths_are_posix_and_relative(tmp_path: Path) -> None:
    _make_project(tmp_path)

    layout = reconcile_manifest(tmp_path).layout

    for path in (layout.composition_root, layout.config_file, layout.tests_dir):
        assert "\\" not in path, "layout paths must be POSIX-normalised"
        assert not os.path.isabs(path), "layout paths must be project-root-relative"


def test_reconcile_non_literal_domain_name_is_underivable(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        domain_py=(
            "from protean.domain import Domain\n\n"
            'NAME = "computed"\n'
            "myproj = Domain(name=NAME)\n"
        ),
    )

    manifest = reconcile_manifest(tmp_path)

    assert manifest.domain_name is None
    assert manifest.package_name == "myproj"


def test_reconcile_raises_when_no_composition_root(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()

    with pytest.raises(ValueError, match="No composition root"):
        reconcile_manifest(tmp_path)


def test_reconcile_raises_when_two_composition_roots(tmp_path: Path) -> None:
    _make_project(tmp_path, package="one", domain="one")
    second = tmp_path / "src" / "two"
    second.mkdir()
    (second / "domain.py").write_text(
        DOMAIN_PY_TEMPLATE.format(package="two", domain="two"), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Ambiguous composition root"):
        reconcile_manifest(tmp_path)


def test_reconcile_derives_domain_name_from_attribute_call(tmp_path: Path) -> None:
    # Domain called as an attribute: protean.Domain(name="X").
    _make_project(
        tmp_path,
        domain_py='import protean\n\nmyproj = protean.Domain(name="Attributed")\n',
    )

    assert reconcile_manifest(tmp_path).domain_name == "Attributed"


def test_reconcile_skips_calls_that_are_not_domain(tmp_path: Path) -> None:
    # A non-Domain call precedes the real one; it must be skipped, not matched.
    _make_project(
        tmp_path,
        domain_py=(
            "from protean.domain import Domain\n\n"
            'print("booting")\n'
            'myproj = Domain(name="Skipped")\n'
        ),
    )

    assert reconcile_manifest(tmp_path).domain_name == "Skipped"


def test_reconcile_ignores_domain_call_on_computed_callable(tmp_path: Path) -> None:
    # The only Domain call is reached through a subscript, so its callable is
    # neither a Name nor an Attribute node. domain_name degrades to None.
    _make_project(
        tmp_path,
        domain_py=(
            "from protean.domain import Domain\n\n"
            "builders = [Domain]\n"
            'myproj = builders[0](name="Computed")\n'
        ),
    )

    manifest = reconcile_manifest(tmp_path)

    assert manifest.domain_name is None
    assert manifest.package_name == "myproj"


def test_reconcile_skips_domain_keyword_that_is_not_name(tmp_path: Path) -> None:
    # A non-name keyword precedes name=; the loop must skip it and still resolve.
    _make_project(
        tmp_path,
        domain_py=(
            "from protean.domain import Domain\n\n"
            'myproj = Domain(identity_type="uuid", name="Named")\n'
        ),
    )

    assert reconcile_manifest(tmp_path).domain_name == "Named"


def test_reconcile_domain_name_underivable_on_syntax_error(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        domain_py="from protean.domain import Domain\n\nmyproj = Domain(name=\n",
    )

    manifest = reconcile_manifest(tmp_path)

    assert manifest.domain_name is None
    assert manifest.package_name == "myproj"


def test_derive_domain_name_returns_none_for_unreadable_file(tmp_path: Path) -> None:
    # A path that cannot be read (here, missing) degrades to None, never raises.
    assert _derive_domain_name(tmp_path / "nonexistent.py") is None


# --------------------------------------------------------------------------- #
# write_manifest / load_stored_manifest — persist and round-trip              #
# --------------------------------------------------------------------------- #


def test_write_then_load_returns_matching_manifest(tmp_path: Path) -> None:
    _make_project(tmp_path, package="acme", domain="Acme")

    assert not (tmp_path / ".protean").exists()
    path = write_manifest(tmp_path)

    assert path == (tmp_path / ".protean" / "project.json").resolve()
    loaded = load_stored_manifest(tmp_path / ".protean")
    assert loaded is not None
    manifest, loaded_path = loaded
    assert loaded_path == tmp_path / ".protean" / "project.json"
    assert manifest.package_name == "acme"
    assert manifest.domain_name == "Acme"
    assert manifest.layout.composition_root == "src/acme/domain.py"


def test_write_is_sorted_with_trailing_newline(tmp_path: Path) -> None:
    _make_project(tmp_path)

    path = write_manifest(tmp_path)
    content = path.read_text(encoding="utf-8")

    assert content.endswith("\n")
    data = json.loads(content)
    assert content == json.dumps(data, indent=2, sort_keys=True) + "\n"


def test_write_does_not_clobber_existing_protean_siblings(tmp_path: Path) -> None:
    _make_project(tmp_path)
    protean_dir = tmp_path / ".protean"
    protean_dir.mkdir()
    (protean_dir / "config.toml").write_text("keep = true\n", encoding="utf-8")
    (protean_dir / "ir.json").write_text('{"keep": true}\n', encoding="utf-8")

    write_manifest(tmp_path)

    assert (protean_dir / "config.toml").read_text(encoding="utf-8") == "keep = true\n"
    assert (protean_dir / "ir.json").read_text(encoding="utf-8") == '{"keep": true}\n'


def test_manifest_dict_round_trips(tmp_path: Path) -> None:
    _make_project(tmp_path, package="acme", domain="Acme")
    manifest = reconcile_manifest(tmp_path)

    assert ProjectManifest.from_dict(manifest.to_dict()) == manifest


def test_manifest_dict_round_trips_with_none_domain(tmp_path: Path) -> None:
    manifest = ProjectManifest(
        manifest_version=MANIFEST_VERSION,
        package_name="acme",
        domain_name=None,
        layout=ProjectLayout(
            composition_root="src/acme/domain.py",
            config_file="src/acme/domain.toml",
            tests_dir="tests",
        ),
    )

    assert ProjectManifest.from_dict(manifest.to_dict()) == manifest


def test_load_stored_manifest_missing_returns_none(tmp_path: Path) -> None:
    (tmp_path / ".protean").mkdir()

    assert load_stored_manifest(tmp_path / ".protean") is None


def test_load_stored_manifest_invalid_json_raises(tmp_path: Path) -> None:
    protean_dir = tmp_path / ".protean"
    protean_dir.mkdir()
    (protean_dir / "project.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid JSON"):
        load_stored_manifest(protean_dir)


def test_load_stored_manifest_unreadable_raises(tmp_path: Path) -> None:
    protean_dir = tmp_path / ".protean"
    protean_dir.mkdir()
    # A directory stands where project.json is expected: it exists but reading it
    # raises OSError, which must surface as a ValueError.
    (protean_dir / "project.json").mkdir()

    with pytest.raises(ValueError, match="Could not read"):
        load_stored_manifest(protean_dir)


def test_load_stored_manifest_malformed_shape_raises(tmp_path: Path) -> None:
    protean_dir = tmp_path / ".protean"
    protean_dir.mkdir()
    (protean_dir / "project.json").write_text(
        json.dumps({"manifest_version": "1.0"}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Malformed manifest"):
        load_stored_manifest(protean_dir)


# --------------------------------------------------------------------------- #
# check_manifest_drift — derived, verifiable, never authoritative             #
# --------------------------------------------------------------------------- #


def test_drift_reports_match_for_a_fresh_manifest(tmp_path: Path) -> None:
    _make_project(tmp_path)
    write_manifest(tmp_path)

    result = check_manifest_drift(tmp_path)

    assert result.status == ManifestDriftStatus.MATCH
    assert result.divergences == ()
    assert result.manifest_file == (tmp_path / ".protean" / "project.json").resolve()


def test_drift_reports_no_manifest_when_absent(tmp_path: Path) -> None:
    _make_project(tmp_path)

    result = check_manifest_drift(tmp_path)

    assert result.status == ManifestDriftStatus.NO_MANIFEST
    assert result.divergences == ()
    assert result.manifest_file is None


def test_drift_on_renamed_package_directory_changes_nothing(tmp_path: Path) -> None:
    _make_project(tmp_path, package="myproj", domain="myproj")
    manifest_path = write_manifest(tmp_path)
    before = manifest_path.read_bytes()

    # Rename the package directory; domain.py (name="myproj") moves with it.
    (tmp_path / "src" / "myproj").rename(tmp_path / "src" / "renamed")

    result = check_manifest_drift(tmp_path)

    assert result.status == ManifestDriftStatus.DRIFTED
    drifted_fields = {d.field for d in result.divergences}
    assert "package_name" in drifted_fields
    assert "layout.composition_root" in drifted_fields
    assert "layout.config_file" in drifted_fields
    # domain_name is still "myproj" in the moved file, so it does not drift.
    assert "domain_name" not in drifted_fields
    # The check mutates nothing on disk.
    assert manifest_path.read_bytes() == before


def test_hand_edited_manifest_reads_as_drift_and_disk_wins(tmp_path: Path) -> None:
    _make_project(tmp_path, package="myproj", domain="myproj")
    manifest_path = write_manifest(tmp_path)

    # Hand-edit the stored manifest so every field disagrees with disk.
    tampered = json.loads(manifest_path.read_text(encoding="utf-8"))
    tampered["package_name"] = "hacked"
    tampered["domain_name"] = "Hacked"
    tampered["layout"]["composition_root"] = "src/hacked/domain.py"
    manifest_path.write_text(
        json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    before = manifest_path.read_bytes()

    result = check_manifest_drift(tmp_path)

    assert result.status == ManifestDriftStatus.DRIFTED
    by_field = {d.field: d for d in result.divergences}
    # Every tampered field is reported, and the recomputed value equals disk,
    # proving the stored file is never honoured over the code.
    assert by_field["package_name"].stored == "hacked"
    assert by_field["package_name"].recomputed == "myproj"
    assert by_field["domain_name"].stored == "Hacked"
    assert by_field["domain_name"].recomputed == "myproj"
    assert by_field["layout.composition_root"].recomputed == "src/myproj/domain.py"
    # The check changed nothing on disk.
    assert manifest_path.read_bytes() == before


def test_non_literal_domain_name_reads_as_drift_against_stored_literal(
    tmp_path: Path,
) -> None:
    _make_project(tmp_path, package="myproj", domain="myproj")
    manifest_path = write_manifest(tmp_path)

    # Now make domain_name underivable on disk while the stored literal remains.
    (tmp_path / "src" / "myproj" / "domain.py").write_text(
        "from protean.domain import Domain\n\n"
        'NAME = "myproj"\n'
        "myproj = Domain(name=NAME)\n",
        encoding="utf-8",
    )

    result = check_manifest_drift(tmp_path)

    assert result.status == ManifestDriftStatus.DRIFTED
    by_field = {d.field: d for d in result.divergences}
    assert by_field["domain_name"].stored == "myproj"
    assert by_field["domain_name"].recomputed is None
    assert manifest_path.exists()


# --------------------------------------------------------------------------- #
# CLI wiring — `protean new` writes the manifest, `--pretend` does not         #
# --------------------------------------------------------------------------- #


def test_protean_new_writes_a_loadable_manifest() -> None:
    with isolated_filesystem() as project_dir:
        result = runner.invoke(
            app,
            [
                "new",
                "foobar",
                "-o",
                project_dir,
                "--defaults",
                "--skip-setup",
                "-d",
                "author_name=John Doe",
                "-d",
                "author_email=john@doe.com",
            ],
        )

        assert result.exit_code == 0, result.output
        manifest_file = Path(project_dir) / "foobar" / ".protean" / "project.json"
        assert manifest_file.is_file()
        loaded = load_stored_manifest(manifest_file.parent)
        assert loaded is not None
        manifest, _ = loaded
        assert manifest.package_name == "foobar"
        assert manifest.layout.composition_root == "src/foobar/domain.py"


def test_protean_new_pretend_writes_no_manifest() -> None:
    with isolated_filesystem() as project_dir:
        result = runner.invoke(
            app,
            [
                "new",
                "foobar",
                "-o",
                project_dir,
                "--pretend",
                "--defaults",
                "-d",
                "author_name=John Doe",
                "-d",
                "author_email=john@doe.com",
            ],
        )

        assert result.exit_code == 0, result.output
        assert not (Path(project_dir) / "foobar").exists()
