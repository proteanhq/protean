"""Run the example on ``docs/guides/write-an-adapter/cache.md``.

The example is the ``delegating_cache`` package. The cache registry
stores the adapter by its dotted import path, so the package's folder goes on
``sys.path`` and the test imports it by name.
"""

import importlib
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterator

import pytest

from tests.docs.support import (
    DOCS,
    DOCS_SRC,
    REPO_ROOT,
    domain_from_config,
    outcome_counts,
)

_EXAMPLE = DOCS_SRC / "guides" / "write-an-adapter" / "cache"
if str(_EXAMPLE) not in sys.path:
    sys.path.insert(0, str(_EXAMPLE))

import delegating_cache

from protean.adapters.cache.memory import MemoryCache
from protean.core.projection import BaseProjection
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.infra.cache import DEFAULT_TTL
from protean.port.cache import CacheCapabilities
from tests.support.snippets import extract_toml_blocks

pytestmark = pytest.mark.no_test_domain

# The suite runs in a few seconds. The limit stops a run that hangs.
_CONFORMANCE_TIMEOUT = 300

_PAGE = DOCS / "guides" / "write-an-adapter" / "cache.md"

# Every guide under docs/guides/write-an-adapter/ has these sections, in this
# order.
_SECTIONS = [
    "What does the adapter implement?",
    "Declare capabilities",
    "Write the adapter",
    "Register it with an entry point",
    "Run the conformance suite",
    "Configure it in `domain.toml`",
]

# For each flag, a node id prefix that matches only tests needing the flag,
# from the markers in tests/conformance/cache/. SHARED and DURABLE share a
# module, so their prefixes name the one test each flag gates.
_SHARED_AND_DURABLE = "test_shared_and_durable.py::"
_FLAG_TESTS = {
    CacheCapabilities.KEY_VALUE: "test_roundtrip.py::",
    CacheCapabilities.TTL: "test_ttl.py::",
    CacheCapabilities.PATTERN_MATCH: "test_key_patterns.py::",
    CacheCapabilities.SHARED: _SHARED_AND_DURABLE
    + "test_a_second_adapter_from_the_same_config_reads_the_first_ones_writes",
    CacheCapabilities.DURABLE: _SHARED_AND_DURABLE
    + "test_an_entry_outlasts_the_adapter_that_wrote_it",
}


def _run_conformance_suite() -> subprocess.CompletedProcess[str]:
    """Run the cache suite against the example, as a contributor would."""
    pythonpath = [str(_EXAMPLE)]
    if os.environ.get("PYTHONPATH"):
        pythonpath.append(os.environ["PYTHONPATH"])
    # The outer run's pytest and xdist settings must not reach the child run.
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("PYTEST_") and name != "PROTEAN_ENV"
    }
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    try:
        return _run_pytest(env)
    except subprocess.TimeoutExpired as exc:
        # pytest shows the exception message and not its attributes, so the
        # output the child wrote so far goes into the message.
        output = _text(exc.stdout) + _text(exc.stderr)
        raise TimeoutError(
            f"The conformance run took longer than {_CONFORMANCE_TIMEOUT}s. "
            f"Output so far:\n{output}"
        ) from exc


def _text(stream: str | bytes | None) -> str:
    if isinstance(stream, bytes):
        return stream.decode(errors="replace")
    return stream or ""


def _run_pytest(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/conformance/cache",
            "-p",
            "delegating_cache",
            "--port",
            "cache",
            "--adapter",
            "delegating_memory",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "-q",
            "-rA",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=_CONFORMANCE_TIMEOUT,
    )


@pytest.fixture(scope="module")
def conformance_run() -> subprocess.CompletedProcess[str]:
    return _run_conformance_suite()


@pytest.fixture
def domain(tmp_path) -> Iterator[Domain]:
    domain = domain_from_config("guides/write-an-adapter/cache/domain.toml", tmp_path)
    domain.init(traverse=False)
    with domain.domain_context():
        yield domain


def test_conformance_suite_passes_against_the_example(conformance_run):
    output = conformance_run.stdout + conformance_run.stderr

    assert conformance_run.returncode == 0, output
    counts = outcome_counts(conformance_run)
    assert counts.get("passed", 0) > 0, output
    assert "failed" not in counts and "errors" not in counts, output


def test_every_single_flag_has_conformance_tests():
    # Iterating a Flag yields its single flags only, not composites like LOCAL.
    assert set(CacheCapabilities) == set(_FLAG_TESTS)


def test_conformance_run_executes_the_tests_the_declared_flags_gate(
    conformance_run, domain
):
    declared = domain.caches["default"]._adapter.capabilities

    for flag in CacheCapabilities:
        skip_line = f"delegating_memory does not declare {flag.name}"
        passed_line = f"PASSED tests/conformance/cache/{_FLAG_TESTS[flag]}"
        if flag in declared:
            assert skip_line not in conformance_run.stdout, flag.name
            assert passed_line in conformance_run.stdout, flag.name
        else:
            # The suite reports a flag the example does not declare as a skip.
            # Seeing that line shows the check above reads the real skip text.
            assert skip_line in conformance_run.stdout, flag.name
            assert passed_line not in conformance_run.stdout, flag.name


def test_example_declares_the_memory_cache_flags(domain):
    adapter = domain.caches["default"]._adapter

    assert adapter.capabilities == CacheCapabilities.LOCAL
    assert adapter.capabilities == adapter._delegate.capabilities


def test_domain_toml_builds_the_example_adapter(domain):
    adapter = domain.caches["default"]._adapter

    assert isinstance(adapter, delegating_cache.DelegatingCache)
    assert isinstance(adapter._delegate, MemoryCache)


class Summary(BaseProjection):
    summary_id: Identifier(identifier=True)
    title: String()


def test_ttl_from_domain_toml_reaches_get_ttl(tmp_path):
    path = _EXAMPLE / "domain.toml"
    ttl = tomllib.loads(path.read_text(encoding="utf-8"))["caches"]["default"]["TTL"]
    domain = domain_from_config("guides/write-an-adapter/cache/domain.toml", tmp_path)
    domain.register(Summary, cache="default")
    domain.init(traverse=False)

    # The page's TTL differs from the default, so a value near it cannot come
    # from the default.
    assert ttl < DEFAULT_TTL

    with domain.domain_context():
        cache = domain.cache_for(Summary)
        cache.add(Summary(summary_id="1", title="First"))

        remaining = cache.get_ttl(cache.key_for(Summary, "1"))
        # The lower bound allows for the time between the write and the read.
        assert remaining is not None and ttl - 5 < remaining <= ttl


def test_entry_point_names_the_register_function():
    path = _EXAMPLE / "entry-points.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))

    target = data["project"]["entry-points"]["protean.caches"]["delegating_memory"]
    assert target == "delegating_cache:register"

    module_name, attribute = target.split(":")
    resolved = getattr(importlib.import_module(module_name), attribute)
    assert resolved is delegating_cache.register


def test_example_implements_every_port_member():
    cls = delegating_cache.DelegatingCache

    assert cls.__abstractmethods__ == frozenset()


def test_written_entry_reaches_the_delegate(domain):
    adapter = domain.caches["default"]._adapter
    adapter.put("summary:::1", {"title": "First"}, 60.0)

    assert adapter._delegate.get("summary:::1") == {"title": "First"}
    assert adapter.get("summary:::1") == {"title": "First"}


class _RecordingCache(MemoryCache):
    """A memory cache that reports itself unreachable and records `close`."""

    closed = False

    def ping(self) -> bool:
        return False

    def close(self) -> None:
        self.closed = True


def test_connection_members_reach_the_delegate(domain):
    adapter = domain.caches["default"]._adapter
    assert adapter.get_connection() is adapter._delegate.get_connection()

    delegate = _RecordingCache(adapter.name, domain, adapter.config)
    adapter._delegate = delegate

    assert adapter.ping() is False
    adapter.close()
    assert delegate.closed


def test_pattern_reads_reach_the_delegate(domain):
    adapter = domain.caches["default"]._adapter
    adapter._delegate.put("summary:::2", {"title": "Second"}, None)
    adapter._delegate.put("summary:::1", {"title": "First"}, None)
    adapter._delegate.put("order:::1", {"title": "Order"}, None)

    assert adapter.keys_matching("summary:::*") == ["summary:::1", "summary:::2"]
    assert adapter.count_matching("summary:::*") == 2

    adapter.delete_matching("summary:::*")
    assert adapter._delegate.keys_matching("*") == ["order:::1"]


def test_page_has_the_guide_sections_in_order():
    text = _PAGE.read_text(encoding="utf-8")

    headings = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    assert headings == _SECTIONS


def test_each_toml_block_on_the_page_includes_one_example_file():
    blocks = extract_toml_blocks(_PAGE.read_text(encoding="utf-8"))
    assert blocks

    includes = sorted(block.source.strip() for block in blocks)
    assert includes == [
        '--8<-- "guides/write-an-adapter/cache/domain.toml"',
        '--8<-- "guides/write-an-adapter/cache/entry-points.toml"',
    ]
