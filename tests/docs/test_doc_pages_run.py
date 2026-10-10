"""Run every Python block on every documentation page.

Each page under ``docs/`` (outside ``docs/adr/`` and ``docs/api/``) that has a
``python`` or ``py`` block runs through the runner in
``tests/support/snippets.py``: the blocks of one page run top to bottom in one
namespace, and the page's domains are initialized after the last block. A
``--8<-- "<spec>"`` line inside a block is replaced with the code it includes
from ``docs_src`` or ``examples`` before the block runs, so a later inline
block can use an element an include defined.

A block whose first line is ``# fragment`` is not run. The marker is for a
block that is not meant to run: a signature, part of a class or a method, a
wrong example shown on purpose, code that needs a service the core lane does
not run, or code that starts a server or otherwise blocks.
A page whose blocks fail goes on ``ALLOWLIST``. Marking a block ``# fragment``
to hide an error is not allowed.

The allowlist is strict. A listed page may fail. A listed page whose blocks all
pass fails until its entry is removed, and so does an entry for a page that is
gone or has no Python blocks.

Two checks have no allowlist: every block that is not a fragment must parse,
and every include must resolve. A ``python`` block that starts with ``>>>`` is
a REPL transcript and must use a ``pycon`` fence.

All pages run once, in one child interpreter, and each page is its own test
case, so a failure names the page.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tests.docs.support import DOCS, REPO_ROOT
from tests.support.snippets import (
    evaluate_one,
    extract_blocks,
    include_expander,
    parse_problems,
    run_snippets,
)

pytestmark = pytest.mark.no_test_domain

# The folders an include path is relative to, searched in order. They must
# match ``pymdownx.snippets.base_path`` in mkdocs.yml.
SNIPPET_BASES = (REPO_ROOT / "docs_src", REPO_ROOT / "examples")

# Folders under docs/ whose pages are not run: the decision records keep their
# code as it was when the decision was made, and the API pages are generated.
EXCLUDED = frozenset({"adr", "api"})

expand = include_expander(SNIPPET_BASES)


def in_scope(path: Path) -> bool:
    return path.relative_to(DOCS).parts[0] not in EXCLUDED


def discover_pages(docs: Path = DOCS) -> list[Path]:
    """Every in-scope page under ``docs`` holding a Python block."""
    return sorted(
        path
        for path in docs.rglob("*.md")
        if in_scope(path) and extract_blocks(path.read_text(encoding="utf-8"))
    )


PAGES = discover_pages()
LABELS = [path.relative_to(DOCS).as_posix() for path in PAGES]

# Pages with a block that fails today, relative to docs/. Fix the page, then
# delete its entry.
ALLOWLIST: frozenset[str] = frozenset(
    {
        "concepts/async-processing/engine.md",
        "concepts/async-processing/outbox.md",
        "concepts/async-processing/priority-lanes.md",
        "concepts/async-processing/stream-categories.md",
        "concepts/async-processing/subscriptions.md",
        "concepts/building-blocks/choosing-element-types.md",
        "concepts/building-blocks/commands.md",
        "concepts/foundations/invariants.md",
        "concepts/internals/event-sourcing.md",
        "concepts/internals/event-upcasting.md",
        "concepts/internals/field-system.md",
        "concepts/internals/query-system.md",
        "concepts/internals/shadow-fields.md",
        "concepts/observability/logging.md",
        "concepts/philosophy/always-valid.md",
        "concepts/ports-and-adapters/index.md",
        "guides/change-state/application-services.md",
        "guides/change-state/command-handlers.md",
        "guides/change-state/commands.md",
        "guides/change-state/database-models.md",
        "guides/change-state/event-store-setup.md",
        "guides/change-state/persist-aggregates.md",
        "guides/change-state/repositories.md",
        "guides/change-state/retrieve-aggregates.md",
        "guides/change-state/snapshots.md",
        "guides/change-state/temporal-queries.md",
        "guides/change-state/unit-of-work.md",
        "guides/consume-state/projectors.md",
        "guides/domain-behavior/aggregate-mutation.md",
        "guides/domain-behavior/domain-services.md",
        "guides/domain-behavior/error-handling.md",
        "guides/domain-behavior/invariants.md",
        "guides/domain-behavior/message-enrichment.md",
        "guides/domain-behavior/message-tracing.md",
        "guides/domain-behavior/raising-events.md",
        "guides/domain-behavior/status-transitions.md",
        "guides/domain-behavior/validations.md",
        "guides/getting-started/es-tutorial/02-deposits-and-withdrawals.md",
        "guides/getting-started/es-tutorial/03-commands-and-pipeline.md",
        "guides/getting-started/es-tutorial/04-business-rules.md",
        "guides/getting-started/es-tutorial/05-testing-the-ledger.md",
        "guides/getting-started/es-tutorial/06-account-dashboard.md",
        "guides/getting-started/es-tutorial/07-reacting-to-events.md",
        "guides/getting-started/es-tutorial/08-going-async.md",
        "guides/getting-started/es-tutorial/09-transferring-funds.md",
        "guides/getting-started/es-tutorial/10-entities-inside-aggregates.md",
        "guides/getting-started/es-tutorial/11-event-upcasting.md",
        "guides/getting-started/es-tutorial/12-snapshots.md",
        "guides/getting-started/es-tutorial/13-temporal-queries.md",
        "guides/getting-started/es-tutorial/14-connecting-outside-world.md",
        "guides/getting-started/es-tutorial/16-message-tracing.md",
        "guides/getting-started/es-tutorial/19-priority-lanes.md",
        "guides/getting-started/es-tutorial/20-rebuilding-projections.md",
        "guides/getting-started/es-tutorial/22-the-full-picture.md",
        "guides/getting-started/tutorial/02-fields-and-value-objects.md",
        "guides/getting-started/tutorial/03-entities-and-associations.md",
        "guides/getting-started/tutorial/04-business-rules.md",
        "guides/getting-started/tutorial/05-commands.md",
        "guides/getting-started/tutorial/06-events-and-reactions.md",
        "guides/getting-started/tutorial/07-projections.md",
        "guides/getting-started/tutorial/09-project-structure.md",
        "guides/getting-started/tutorial/10-api.md",
        "guides/getting-started/tutorial/11-testing.md",
        "guides/getting-started/tutorial/12-going-async.md",
        "guides/getting-started/tutorial/13-domain-services.md",
        "guides/getting-started/tutorial/14-subscribers.md",
        "guides/getting-started/tutorial/16-message-tracing.md",
        "guides/getting-started/tutorial/17-dead-letter-queues.md",
        "guides/getting-started/tutorial/19-priority-lanes.md",
        "guides/getting-started/tutorial/20-process-managers.md",
        "guides/getting-started/tutorial/21-query-patterns.md",
        "guides/testing/application-tests.md",
        "guides/testing/domain-model-tests.md",
        "guides/testing/event-sourcing-tests.md",
        "guides/testing/fixtures-and-patterns.md",
        "guides/testing/integration-tests.md",
        "guides/testing/query-shape-tests.md",
        "patterns/application-service-vs-command-handler.md",
        "patterns/calling-external-systems-from-handlers.md",
        "patterns/classify-async-processing-errors.md",
        "patterns/cloudevents-interoperability.md",
        "patterns/command-idempotency.md",
        "patterns/connect-concepts-across-domains.md",
        "patterns/consuming-events-from-other-domains.md",
        "patterns/coordinating-long-running-processes.md",
        "patterns/design-events-for-consumers.md",
        "patterns/designing-for-concurrent-event-processing.md",
        "patterns/eventual-consistency-in-uis.md",
        "patterns/event-versioning-and-evolution.md",
        "patterns/fact-events-as-integration-contracts.md",
        "patterns/idempotent-event-handlers.md",
        "patterns/index-aggregates-for-query-paths.md",
        "patterns/message-enrichment.md",
        "patterns/message-tracing.md",
        "patterns/model-reference-data.md",
        "patterns/multi-tenancy.md",
        "patterns/organize-by-domain-concept.md",
        "patterns/projection-granularity.md",
        "patterns/projection-rebuilds-as-deployment.md",
        "patterns/publishing-events-to-external-brokers.md",
        "patterns/replace-primitives-with-value-objects.md",
        "patterns/running-data-migrations-with-priority-lanes.md",
        "patterns/setting-up-and-tearing-down-database-for-tests.md",
        "patterns/sharing-event-classes-across-domains.md",
        "patterns/temporal-queries.md",
        "patterns/testing-domain-logic-in-isolation.md",
        "patterns/testing-event-driven-flows.md",
        "patterns/thin-handlers-rich-domain.md",
        "patterns/track-audit-fields.md",
        "patterns/validation-layering.md",
        "reference/cli/data/projection.md",
        "reference/cli/data/snapshot.md",
        "reference/compatibility/index.md",
        "reference/init-diagnostics.md",
        "reference/logging.md",
        "reference/migration/v0-15.md",
        "reference/migration/v0-17.md",
        "reference/migration/v0-18.md",
        "reference/server/configuration.md",
        "reference/server/observability.md",
        "reference/server/sequential-by.md",
        "reference/server/subscription-types.md",
        "reference/troubleshooting.md",
        "why-protean.md",
    }
)


@pytest.fixture(scope="module")
def page_results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict]:
    results = run_snippets(
        DOCS, PAGES, tmp_path_factory.mktemp("doc-pages"), expand=expand
    )
    assert [r["file"] for r in results] == LABELS
    return {r["file"]: r for r in results}


@pytest.mark.parametrize("page", LABELS)
def test_page_runs_or_is_allowlisted(page: str, page_results: dict[str, dict]):
    problems = evaluate_one(page_results[page], ALLOWLIST)
    assert problems == [], "\n".join(problems)


def test_every_allowlisted_page_exists_and_has_python_blocks():
    stale = sorted(ALLOWLIST - set(LABELS))
    assert stale == [], (
        "on the allowlist but not a page with python blocks; remove the entry: "
        + ", ".join(stale)
    )


def test_every_block_parses_and_every_include_resolves():
    problems = [
        problem
        for path, label in zip(PAGES, LABELS, strict=True)
        for problem in parse_problems(path, label, expand)
    ]
    assert problems == [], "\n".join(problems)


# Wider than the extractor's fence pattern on purpose: any case, ``python3``
# and ``{.python}``. A docs page using one of those forms breaks the count.
_ANY_PY_FENCE = re.compile(
    r"^\s*(`{3,}|~{3,})\s*(python3?|py3?|\{\s*\.py(thon)?\b[^}]*\})(\s.*)?$",
    re.IGNORECASE,
)


def test_page_discovery_is_not_vacuous():
    blocks = sum(len(extract_blocks(p.read_text(encoding="utf-8"))) for p in PAGES)
    # Count every line that opens a Python fence in any form, so a variant
    # the extractor skips breaks the count.
    independent = sum(
        1
        for path in DOCS.rglob("*.md")
        if in_scope(path)
        for line in path.read_text(encoding="utf-8").splitlines()
        if _ANY_PY_FENCE.match(line)
    )
    assert blocks == independent
    assert len(PAGES) >= 200
    assert blocks >= 1400


class _MkDocsLoader(yaml.SafeLoader):
    """Read mkdocs.yml without building the ``!!python/name`` objects it names."""


_MkDocsLoader.add_multi_constructor(
    "tag:yaml.org,2002:python/", lambda loader, suffix, node: None
)


def test_snippet_bases_match_mkdocs():
    config = yaml.load(
        (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8"), Loader=_MkDocsLoader
    )
    options = next(
        entry["pymdownx.snippets"]
        for entry in config["markdown_extensions"]
        if isinstance(entry, dict) and "pymdownx.snippets" in entry
    )
    assert [REPO_ROOT / base for base in options["base_path"]] == list(SNIPPET_BASES)
