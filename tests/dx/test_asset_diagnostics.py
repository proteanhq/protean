"""Run ``Domain.check`` on every DX-pack skill asset and hold its findings.

``tests/dx/test_examples.py`` proves each ``skills/*/assets/*.py`` initializes.
This test runs ``Domain.check(traverse=False)`` on each asset's domains and
collects every validation error and every diagnostic at level ``warning`` or
``error``. When validation passes but the IR fails to build, ``check`` returns
no diagnostics, so the test builds the IR itself and records
``IR_BUILD_FAILED`` for that asset.

Four completeness codes are ignored for every asset. A teaching asset shows one
concept and is not a whole application, so an aggregate without a command
handler or an event nobody handles is expected there. Every other code must
appear on the ``ALLOWLIST`` for that asset, and the allowlist is strict: an
entry whose code no longer fires fails the test, so fixing an asset means
deleting its entry.

Some assets show a problem on purpose (the "before" side of a refactoring, an
unclosed saga, the audit skill's sample codebase). They are exempt by name.

The assets run in one child interpreter, each as its own file-backed module,
so their registrations stay out of this test process and source-reading
diagnostics can find each asset's source.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from protean import dx

pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
SKILLS_ROOT = PACK_ROOT / dx.SKILLS_DIR

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the check runner needs a real "
        "directory to execute assets by path",
        allow_module_level=True,
    )

COMPLETENESS_CODES = frozenset(
    {
        "AGGREGATE_WITHOUT_COMMAND_HANDLER",
        "PROJECTION_WITHOUT_PROJECTOR",
        "UNHANDLED_EVENT",
        "UNUSED_COMMAND",
    }
)

# Recorded, in place of a diagnostic code, for a domain whose validation passes
# but whose IR fails to build. ``Domain.check`` returns no diagnostics then, so
# without this code the asset would look clean.
IR_BUILD_FAILED = "IR_BUILD_FAILED"

EXEMPT_NAMES = frozenset({"saga_before_unclosed.py", "audit_sample_codebase.py"})

# (asset path relative to the skills root, diagnostic code). Each entry is a
# finding the asset has today. Fix the asset, then delete the entry.
ALLOWLIST = frozenset(
    {
        ("domain-service/assets/domain_service_callable.py", IR_BUILD_FAILED),
        ("domain-service/assets/domain_service_class_methods.py", IR_BUILD_FAILED),
        (
            "domain-service/assets/domain_service_instance_methods.py",
            IR_BUILD_FAILED,
        ),
        ("domain-service/assets/domain_service_with_invariants.py", IR_BUILD_FAILED),
        (
            "repository/assets/repository_counting_and_nulls.py",
            "UNINDEXED_FILTER_PATH",
        ),
        ("repository/assets/repository_custom.py", "UNINDEXED_FILTER_PATH"),
        ("repository/assets/repository_with_database.py", "UNINDEXED_FILTER_PATH"),
    }
)


def is_exempt(path: Path) -> bool:
    """True for an asset that shows a problem on purpose."""
    return path.name.endswith("_before.py") or path.name in EXEMPT_NAMES


def discover_assets(skills_root: Path) -> list[Path]:
    """Every non-exempt ``*/assets/*.py`` under ``skills_root``, sorted.

    A package ``__init__.py`` and the pytest ``conftest.py`` define no domain
    and are skipped.
    """
    return sorted(
        path
        for path in skills_root.glob("*/assets/*.py")
        if path.name not in ("__init__.py", "conftest.py") and not is_exempt(path)
    )


# The child-interpreter runner. argv[1] is the skills root, argv[2] a JSON list
# of asset paths, argv[3] the report path. For each asset it records the codes
# ``Domain.check`` returns at level warning or error, ``IR_BUILD_FAILED`` when
# the IR does not build, or the exception that stopped it. It writes a file, not a stream, so start-up logging on stderr
# cannot corrupt the report.
_RUNNER = """
import importlib.util
import json
import pathlib
import sys

from protean.domain import Domain

skills_root = pathlib.Path(sys.argv[1])
assets = [pathlib.Path(p) for p in json.loads(sys.argv[2])]
report_path = pathlib.Path(sys.argv[3])
codes = {}
crashes = {}
ir_failures = {}
for index, path in enumerate(assets):
    label = path.relative_to(skills_root).as_posix()
    name = "_dx_check_%d_" % index
    try:
        # A file-backed module that stays in ``sys.modules`` while it is
        # checked: rules that read an element's source resolve its module
        # with ``find_spec``, which finds nothing once the module is gone.
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        namespace = vars(module)
        domains = {id(v): v for v in namespace.values() if isinstance(v, Domain)}
        if not domains:
            raise RuntimeError("asset defines no Domain")
        found = set()
        for domain in domains.values():
            report = domain.check(traverse=False)
            found.update(entry["code"] for entry in report["errors"])
            found.update(
                entry["code"]
                for entry in report["diagnostics"]
                if entry.get("level") in ("warning", "error")
            )
            if not report["errors"]:
                # ``check`` drops an IR build failure and returns no
                # diagnostics, so build the IR again to see the failure.
                try:
                    domain.to_ir()
                except Exception as exc:
                    found.add("IR_BUILD_FAILED")
                    ir_failures[label] = "%s: %s" % (type(exc).__name__, exc)
        codes[label] = sorted(found)
    except Exception as exc:  # report the asset, then keep going
        crashes[label] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        sys.modules.pop(name, None)
report = {"codes": codes, "crashes": crashes, "ir_failures": ir_failures}
report_path.write_text(json.dumps(report))
"""


def collect_codes(skills_root: Path, assets: list[Path], tmp_path: Path) -> dict:
    """Run ``Domain.check`` on each asset in a child interpreter.

    Returns ``{"codes": {asset: [code, ...]}, "crashes": {asset: message},
    "ir_failures": {asset: message}}``, with asset paths relative to
    ``skills_root``. An asset in ``ir_failures`` also has ``IR_BUILD_FAILED``
    among its codes.
    """
    report_path = tmp_path / "check-report.json"
    # A report left by an earlier run in the same directory must not pass
    # for this one.
    report_path.unlink(missing_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            # No bytecode: the assets load as file-backed modules, and a
            # ``__pycache__`` beside them would land in the shipped pack.
            "-B",
            "-c",
            _RUNNER,
            str(skills_root),
            json.dumps([str(path) for path in assets]),
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert result.returncode == 0 and report_path.is_file(), (
        f"the check runner crashed before writing its report "
        f"(exit {result.returncode}):\n{result.stderr}"
    )
    return json.loads(report_path.read_text())


def evaluate(report: dict, allowlist: frozenset[tuple[str, str]]) -> list[str]:
    """Compare the collected codes with the allowlist and list the problems."""
    problems = [
        f"{asset}: could not be checked: {message}"
        for asset, message in sorted(report["crashes"].items())
    ]
    found = {
        (asset, code)
        for asset, codes in report["codes"].items()
        for code in codes
        if code not in COMPLETENESS_CODES
    }
    for asset, code in sorted(found - allowlist):
        message = f"{asset}: reports {code}, which is not on the allowlist"
        if code == IR_BUILD_FAILED:
            message += f" ({report['ir_failures'][asset]})"
        problems.append(message)
    checked = set(report["codes"])
    for asset, code in sorted(allowlist - found):
        if asset in checked:
            problems.append(
                f"{asset}: no longer reports {code}; remove ({asset!r}, {code!r}) "
                "from the allowlist"
            )
        else:
            problems.append(
                f"{asset}: is on the allowlist for {code} but was not checked; "
                "remove the entry"
            )
    return problems


def test_asset_discovery_is_not_vacuous():
    assets = discover_assets(SKILLS_ROOT)
    every = [
        path
        for skill in SKILLS_ROOT.iterdir()
        if (skill / "assets").is_dir()
        for path in (skill / "assets").iterdir()
        if path.suffix == ".py" and path.name not in ("__init__.py", "conftest.py")
    ]
    exempt = [path for path in every if is_exempt(path)]
    assert assets, "discovered no assets under the DX pack"
    assert len(assets) == len(every) - len(exempt)
    assert exempt, "the exemption rule matched no asset"
    assert len(assets) >= 120


def test_every_asset_passes_check_or_is_allowlisted(tmp_path):
    assets = discover_assets(SKILLS_ROOT)
    report = collect_codes(SKILLS_ROOT, assets, tmp_path)

    assert len(report["codes"]) + len(report["crashes"]) == len(assets)
    problems = evaluate(report, ALLOWLIST)
    assert problems == [], "asset check findings:\n" + "\n".join(problems)


# --- Negative tests on synthetic skill folders -------------------------------

_FOREIGN_EVENT_ASSET = """
from protean import Domain, handle
from protean.fields import Identifier, String

domain = Domain(name="Foreign")


@domain.aggregate
class Order:
    name = String()


@domain.event(part_of=Order)
class OrderPlaced:
    order_id = Identifier()


@domain.aggregate
class Inventory:
    sku = String()


@domain.event_handler(part_of=Inventory)
class InventoryHandler:
    @handle(OrderPlaced)
    def on_placed(self, event):
        pass
"""

_COMPLETENESS_ONLY_ASSET = """
from protean import Domain
from protean.fields import String

domain = Domain(name="Lonely")


@domain.aggregate
class Order:
    name = String()
"""


def _write_asset(root: Path, name: str, source: str) -> Path:
    assets_dir = root / "skill" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    path = assets_dir / name
    path.write_text(source, encoding="utf-8")
    return path


def _check(root: Path, tmp_path: Path, allowlist=frozenset()) -> list[str]:
    report = collect_codes(root, discover_assets(root), tmp_path)
    return evaluate(report, allowlist)


def test_an_unlisted_warning_fails_and_names_asset_and_code(tmp_path):
    root = tmp_path / "skills"
    _write_asset(root, "foreign.py", _FOREIGN_EVENT_ASSET)
    assert _check(root, tmp_path) == [
        (
            "skill/assets/foreign.py: reports EVENT_HANDLER_FOREIGN_EVENT, which is "
            "not on the allowlist"
        )
    ]


_UNINDEXED_FILTER_ASSET = """
from protean import Domain
from protean.fields import String

domain = Domain(name="Unindexed")


@domain.aggregate
class Customer:
    email = String()


@domain.repository(part_of=Customer)
class CustomerRepository:
    def by_email(self, email):
        return self._dao.query.filter(email=email).all()
"""


def test_a_warning_read_from_source_is_reported(tmp_path):
    # The rule reads the repository's method body, so it only fires when the
    # asset's module source can be found during ``check``.
    root = tmp_path / "skills"
    _write_asset(root, "unindexed.py", _UNINDEXED_FILTER_ASSET)
    assert _check(root, tmp_path) == [
        (
            "skill/assets/unindexed.py: reports UNINDEXED_FILTER_PATH, which is not "
            "on the allowlist"
        )
    ]
    # Loading an asset as a module must not leave bytecode in the skills tree.
    assert not list(root.rglob("__pycache__"))


def test_a_listed_warning_passes(tmp_path):
    root = tmp_path / "skills"
    _write_asset(root, "foreign.py", _FOREIGN_EVENT_ASSET)
    allowlist = frozenset({("skill/assets/foreign.py", "EVENT_HANDLER_FOREIGN_EVENT")})
    assert _check(root, tmp_path, allowlist) == []


def test_only_completeness_codes_pass_without_an_entry(tmp_path):
    root = tmp_path / "skills"
    _write_asset(root, "lonely.py", _COMPLETENESS_ONLY_ASSET)
    report = collect_codes(root, discover_assets(root), tmp_path)
    # The completeness code really fires; the guard ignores it.
    assert report["codes"] == {
        "skill/assets/lonely.py": ["AGGREGATE_WITHOUT_COMMAND_HANDLER"]
    }
    assert evaluate(report, frozenset()) == []


def test_a_listed_code_that_no_longer_fires_fails(tmp_path):
    root = tmp_path / "skills"
    _write_asset(root, "lonely.py", _COMPLETENESS_ONLY_ASSET)
    allowlist = frozenset({("skill/assets/lonely.py", "EVENT_HANDLER_FOREIGN_EVENT")})
    assert _check(root, tmp_path, allowlist) == [
        (
            "skill/assets/lonely.py: no longer reports EVENT_HANDLER_FOREIGN_EVENT; "
            "remove ('skill/assets/lonely.py', 'EVENT_HANDLER_FOREIGN_EVENT') from "
            "the allowlist"
        )
    ]


def test_a_listed_asset_that_is_gone_fails(tmp_path):
    root = tmp_path / "skills"
    _write_asset(root, "lonely.py", _COMPLETENESS_ONLY_ASSET)
    allowlist = frozenset({("skill/assets/gone.py", "UPCASTER_GAP")})
    assert _check(root, tmp_path, allowlist) == [
        (
            "skill/assets/gone.py: is on the allowlist for UPCASTER_GAP but was not "
            "checked; remove the entry"
        )
    ]


@pytest.mark.parametrize(
    "name", ["thing_before.py", "saga_before_unclosed.py", "audit_sample_codebase.py"]
)
def test_an_exempt_asset_with_a_warning_passes(tmp_path, name):
    root = tmp_path / "skills"
    _write_asset(root, name, _FOREIGN_EVENT_ASSET)
    assert discover_assets(root) == []
    assert _check(root, tmp_path) == []


def test_an_asset_that_raises_is_reported(tmp_path):
    root = tmp_path / "skills"
    _write_asset(root, "lonely.py", _COMPLETENESS_ONLY_ASSET)
    _write_asset(root, "broken.py", "raise ValueError('boom')\n")
    assert _check(root, tmp_path) == [
        "skill/assets/broken.py: could not be checked: ValueError: boom"
    ]


_DUPLICATE_HANDLER_ASSET = """
from protean import Domain, handle
from protean.fields import Identifier, String

domain = Domain(name="Duplicate")


@domain.aggregate
class Order:
    name = String()


@domain.command(part_of=Order)
class PlaceOrder:
    order_id = Identifier()


@domain.command_handler(part_of=Order)
class FirstHandler:
    @handle(PlaceOrder)
    def place(self, command):
        pass


@domain.command_handler(part_of=Order)
class SecondHandler:
    @handle(PlaceOrder)
    def place(self, command):
        pass
"""


def test_a_validation_error_is_reported(tmp_path):
    root = tmp_path / "skills"
    _write_asset(root, "duplicate.py", _DUPLICATE_HANDLER_ASSET)
    assert _check(root, tmp_path) == [
        (
            "skill/assets/duplicate.py: reports IncorrectUsageError, which is not on "
            "the allowlist"
        )
    ]


_IR_FAILURE_ASSET = """
from protean import Domain
from protean.fields import String

domain = Domain(name="Unbuildable")


@domain.aggregate
class Order:
    name = String()


@domain.domain_service(part_of=["Order", "Order"])
class Pricing:
    pass
"""


def test_an_ir_build_failure_is_reported(tmp_path):
    root = tmp_path / "skills"
    _write_asset(root, "unbuildable.py", _IR_FAILURE_ASSET)
    problems = _check(root, tmp_path)
    assert problems == [
        (
            "skill/assets/unbuildable.py: reports IR_BUILD_FAILED, which is not on "
            "the allowlist (AttributeError: 'str' object has no attribute '__module__')"
        )
    ]
    allowlist = frozenset({("skill/assets/unbuildable.py", IR_BUILD_FAILED)})
    assert _check(root, tmp_path, allowlist) == []


def test_an_asset_without_a_domain_is_reported(tmp_path):
    root = tmp_path / "skills"
    _write_asset(root, "plain.py", "x = 1\n")
    assert _check(root, tmp_path) == [
        (
            "skill/assets/plain.py: could not be checked: RuntimeError: asset defines "
            "no Domain"
        )
    ]


def test_every_domain_in_an_asset_is_checked(tmp_path):
    root = tmp_path / "skills"
    source = (
        _COMPLETENESS_ONLY_ASSET.replace("domain =", "first =").replace(
            "@domain.", "@first."
        )
        + _FOREIGN_EVENT_ASSET
    )
    _write_asset(root, "two.py", source)
    assert _check(root, tmp_path) == [
        (
            "skill/assets/two.py: reports EVENT_HANDLER_FOREIGN_EVENT, which is not on "
            "the allowlist"
        )
    ]
