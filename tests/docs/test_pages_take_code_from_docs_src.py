"""The pages converted to docs_src keep their code there.

On each page in ``PAGES``, a Python block either is marked ``# fragment`` or
holds nothing but named-section includes, such as
``--8<-- "guides/x/001.py:full"``. A line-range include or inline code that is
not a fragment fails the test, so a converted page cannot drift back.

On each page under ``docs/reference/adapters/``, a TOML block either is marked
``# fragment`` or holds exactly one include of a whole ``.toml`` file, such as
``--8<-- "adapters/database/sqlite/configuration.toml"``. The tests next to
each page load that file as a ``domain.toml``, so a line-range or section
include fails: the page would show text the tests do not load. The included
file must exist under ``docs_src``, and a string literal in a test module under
``tests/docs/reference/adapters/`` must name its path.

Each guide and pattern page in ``GUIDE_TOML_INCLUDES`` must include the
``docs_src`` TOML files its tests load. Other inline TOML fences stay allowed
on those pages.
"""

from __future__ import annotations

import ast
import re

import pytest

from tests.docs.support import DOCS, DOCS_SRC, REPO_ROOT
from tests.support.snippets import extract_blocks, extract_toml_blocks

pytestmark = pytest.mark.no_test_domain

PAGES = (
    "community/contributing/testing.md",
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
    "concepts/protean-check/behavioral-analysis.md",
    "concepts/protean-check/rules/adapter-call-from-domain.md",
    "concepts/protean-check/rules/unbounded-indexed-string.md",
    "concepts/protean-check/rules/unindexed-filter-path.md",
    "guides/architecture-fitness-functions.md",
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
    "guides/compose-a-domain/activate-domain.md",
    "guides/compose-a-domain/choosing-adapters.md",
    "guides/compose-a-domain/index.md",
    "guides/compose-a-domain/initialize-domain.md",
    "guides/compose-a-domain/inspecting-the-ir.md",
    "guides/compose-a-domain/production-configuration.md",
    "guides/compose-a-domain/register-elements.md",
    "guides/compose-a-domain/schema-generation.md",
    "guides/compose-a-domain/when-to-compose.md",
    "guides/consume-state/cloudevents.md",
    "guides/consume-state/event-handlers.md",
    "guides/consume-state/event-upcasting.md",
    "guides/consume-state/process-managers.md",
    "guides/consume-state/projections.md",
    "guides/consume-state/projectors.md",
    "guides/consume-state/query-handlers.md",
    "guides/consume-state/subscribers.md",
    "guides/domain-behavior/aggregate-mutation.md",
    "guides/domain-behavior/domain-services.md",
    "guides/domain-behavior/error-handling.md",
    "guides/domain-behavior/invariants.md",
    "guides/domain-behavior/message-enrichment.md",
    "guides/domain-behavior/message-tracing.md",
    "guides/domain-behavior/raising-events.md",
    "guides/domain-behavior/status-transitions.md",
    "guides/domain-behavior/validations.md",
    "guides/domain-definition/aggregates.md",
    "guides/domain-definition/entities.md",
    "guides/domain-definition/events.md",
    "guides/domain-definition/fields.md",
    "guides/domain-definition/identity.md",
    "guides/domain-definition/indexes.md",
    "guides/domain-definition/relationships.md",
    "guides/domain-definition/value-objects.md",
    "guides/evolving-events.md",
    "guides/fastapi/http-wide-events.md",
    "guides/fastapi/index.md",
    "guides/fastapi/testing-endpoints.md",
    "guides/getting-started/es-tutorial/01-the-faithful-ledger.md",
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
    "guides/getting-started/es-tutorial/15-fact-events.md",
    "guides/getting-started/es-tutorial/16-message-tracing.md",
    "guides/getting-started/es-tutorial/19-priority-lanes.md",
    "guides/getting-started/es-tutorial/20-rebuilding-projections.md",
    "guides/getting-started/es-tutorial/22-the-full-picture.md",
    "guides/getting-started/tutorial/01-your-first-aggregate.md",
    "guides/getting-started/tutorial/02-fields-and-value-objects.md",
    "guides/getting-started/tutorial/03-entities-and-associations.md",
    "guides/getting-started/tutorial/04-business-rules.md",
    "guides/getting-started/tutorial/05-commands.md",
    "guides/getting-started/tutorial/06-events-and-reactions.md",
    "guides/getting-started/tutorial/07-projections.md",
    "guides/getting-started/tutorial/08-persistence.md",
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
    "guides/multi-domain-applications.md",
    "guides/observability/correlation-and-causation.md",
    "guides/pathways/event-sourcing.md",
    "guides/pathways/migrating-between-architectures.md",
    "guides/server/dead-letter-queues.md",
    "guides/server/error-handling.md",
    "guides/server/external-event-dispatch.md",
    "guides/server/hardening.md",
    "guides/server/index.md",
    "guides/server/logging.md",
    "guides/server/monitoring.md",
    "guides/server/opentelemetry.md",
    "guides/server/outbox.md",
    "guides/server/production-deployment.md",
    "guides/server/tuning-subscriptions.md",
    "guides/server/using-priority-lanes.md",
    "guides/testing/application-tests.md",
    "guides/testing/domain-model-tests.md",
    "guides/testing/event-sourcing-tests.md",
    "guides/testing/fixtures-and-patterns.md",
    "guides/testing/integration-tests.md",
    "guides/testing/query-shape-tests.md",
    "index.md",
    "patterns/aggregate-state-machines.md",
    "patterns/application-service-vs-command-handler.md",
    "patterns/calling-external-systems-from-handlers.md",
    "patterns/classify-async-processing-errors.md",
    "patterns/cloudevents-interoperability.md",
    "patterns/command-idempotency.md",
    "patterns/connect-concepts-across-domains.md",
    "patterns/consuming-events-from-other-domains.md",
    "patterns/coordinating-long-running-processes.md",
    "patterns/creating-identities-early.md",
    "patterns/design-events-for-consumers.md",
    "patterns/design-small-aggregates.md",
    "patterns/designing-for-concurrent-event-processing.md",
    "patterns/encapsulate-state-changes.md",
    "patterns/event-versioning-and-evolution.md",
    "patterns/eventual-consistency-in-uis.md",
    "patterns/fact-events-as-integration-contracts.md",
    "patterns/factory-methods-for-aggregate-creation.md",
    "patterns/idempotent-event-handlers.md",
    "patterns/index-aggregates-for-query-paths.md",
    "patterns/message-enrichment.md",
    "patterns/message-tracing.md",
    "patterns/model-reference-data.md",
    "patterns/multi-tenancy.md",
    "patterns/one-aggregate-per-transaction.md",
    "patterns/optimistic-concurrency-as-design-tool.md",
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
    "reference/adapters/broker/custom-brokers.md",
    "reference/adapters/broker/index.md",
    "reference/adapters/broker/inline.md",
    "reference/adapters/broker/partitioning.md",
    "reference/adapters/broker/redis-pubsub.md",
    "reference/adapters/broker/redis.md",
    "reference/adapters/cache/index.md",
    "reference/adapters/cache/redis.md",
    "reference/adapters/database/custom-databases.md",
    "reference/adapters/database/elasticsearch.md",
    "reference/adapters/database/index.md",
    "reference/adapters/database/memory.md",
    "reference/adapters/database/mssql.md",
    "reference/adapters/database/mysql.md",
    "reference/adapters/database/postgresql.md",
    "reference/adapters/database/sqlite.md",
    "reference/adapters/eventstore/index.md",
    "reference/cli/data/projection.md",
    "reference/cli/data/snapshot.md",
    "reference/cli/ir.md",
    "reference/compatibility/index.md",
    "reference/configuration/index.md",
    "reference/domain-elements/domain-constructor.md",
    "reference/domain-elements/element-decorators.md",
    "reference/domain-elements/identity.md",
    "reference/domain-elements/indexes.md",
    "reference/domain-elements/object-model.md",
    "reference/fields/arguments.md",
    "reference/fields/association-fields.md",
    "reference/fields/container-fields.md",
    "reference/fields/custom-fields.md",
    "reference/fields/defining-fields.md",
    "reference/fields/index.md",
    "reference/fields/simple-fields.md",
    "reference/init-diagnostics.md",
    "reference/logging.md",
    "reference/migration/v0-15.md",
    "reference/migration/v0-17.md",
    "reference/migration/v0-18.md",
    "reference/server/configuration.md",
    "reference/server/hardening.md",
    "reference/server/observability.md",
    "reference/server/sequential-by.md",
    "reference/server/subscription-types.md",
    "reference/server/supervisor.md",
    "reference/stable-surface.md",
    "reference/testing/conformance.md",
    "reference/testing/pytest-plugin.md",
    "reference/troubleshooting.md",
    "why-protean.md",
)

_SECTION_INCLUDE = re.compile(r'^--8<-- "[^":]+\.py:[A-Za-z_][\w-]*"$')
_WHOLE_TOML_INCLUDE = re.compile(r'^--8<-- "(?P<path>[^":]+\.toml)"$')

ADAPTER_PAGES = sorted(
    page.relative_to(DOCS).as_posix()
    for page in (DOCS / "reference/adapters").rglob("*.md")
)


def block_problems(text: str) -> list[str]:
    """Return a line per block that is neither a fragment nor section includes."""
    problems = []
    for block in extract_blocks(text):
        if block.fragment:
            continue
        lines = [line.strip() for line in block.source.splitlines() if line.strip()]
        bad = [line for line in lines if not _SECTION_INCLUDE.match(line)]
        if not lines or bad:
            problems.append(f"line {block.line}: {bad[0] if bad else 'empty block'}")
    return problems


def test_pages_are_sorted_and_unique():
    assert list(PAGES) == sorted(set(PAGES))


@pytest.mark.parametrize("page", PAGES)
def test_page_blocks_are_fragments_or_section_includes(page: str):
    text = (DOCS / page).read_text(encoding="utf-8")

    assert extract_blocks(text), f"{page} has no Python blocks"
    assert block_problems(text) == []


@pytest.mark.parametrize(
    "source",
    [
        '```python\n--8<-- "guides/x/001.py:3:9"\n```\n',
        '```python\n--8<-- "guides/x/001.py"\n```\n',
        "```python\nfrom protean import Domain\n```\n",
    ],
    ids=["line-range", "whole-file", "inline-code"],
)
def test_a_block_that_is_not_a_section_include_is_reported(source: str):
    assert len(block_problems(source)) == 1


def test_a_fragment_or_a_section_include_is_accepted():
    source = (
        '```python\n--8<-- "guides/x/001.py:full"\n```\n'
        "```python\n# fragment\nOrder.place()\n```\n"
    )

    assert block_problems(source) == []


def toml_block_problems(text: str) -> list[str]:
    """Return a line per TOML block that is neither a fragment nor one include."""
    problems = []
    for block in extract_toml_blocks(text):
        if block.fragment:
            continue
        lines = [line.strip() for line in block.source.splitlines() if line.strip()]
        if len(lines) != 1 or not _WHOLE_TOML_INCLUDE.match(lines[0]):
            problems.append(
                f"line {block.line}: {lines[0] if lines else 'empty block'}"
            )
    return problems


@pytest.mark.parametrize("page", ADAPTER_PAGES)
def test_adapter_page_toml_blocks_are_fragments_or_whole_file_includes(page: str):
    text = (DOCS / page).read_text(encoding="utf-8")

    assert toml_block_problems(text) == []


@pytest.mark.parametrize(
    "source",
    [
        '```toml\n[databases.default]\nprovider = "memory"\n```\n',
        '```toml\n--8<-- "adapters/x/domain.toml:1:3"\n```\n',
        '```toml\n--8<-- "adapters/x/domain.toml:default"\n```\n',
        '```toml\n--8<-- "adapters/x/a.toml"\n--8<-- "adapters/x/b.toml"\n```\n',
        '```toml\n--8<-- "adapters/x/001.py"\n```\n',
        '```TOML\n[databases.default]\nprovider = "memory"\n```\n',
        '```toml{.no-copy}\n[databases.default]\nprovider = "memory"\n```\n',
    ],
    ids=[
        "inline",
        "line-range",
        "section",
        "two-includes",
        "not-toml",
        "upper-case",
        "attributes",
    ],
)
def test_a_toml_block_that_is_not_one_whole_file_include_is_reported(source: str):
    assert len(toml_block_problems(source)) == 1


def test_a_toml_fragment_or_a_whole_file_include_is_accepted():
    source = (
        '```toml\n--8<-- "adapters/x/domain.toml"\n```\n'
        '```toml\n# fragment\nconnect_args = { ssl_ca = "ca.pem" }\n```\n'
        '    ```toml\n    --8<-- "adapters/x/nested.toml"\n    ```\n'
    )

    assert toml_block_problems(source) == []


def toml_includes(text: str) -> list[str]:
    """Return the ``docs_src`` paths of the whole-file TOML includes in ``text``."""
    paths = []
    for block in extract_toml_blocks(text):
        if block.fragment:
            continue
        for line in block.source.splitlines():
            match = _WHOLE_TOML_INCLUDE.match(line.strip())
            if match:
                paths.append(match.group("path"))
    return paths


def _strings_in_adapter_page_tests() -> set[str]:
    strings = set()
    for path in (REPO_ROOT / "tests/docs/reference/adapters").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                strings.add(node.value)
    return strings


@pytest.mark.parametrize("page", ADAPTER_PAGES)
def test_adapter_page_toml_includes_name_a_tested_file(page: str):
    paths = toml_includes((DOCS / page).read_text(encoding="utf-8"))
    tested = _strings_in_adapter_page_tests()

    assert [path for path in paths if not (DOCS_SRC / path).is_file()] == []
    assert [path for path in paths if path not in tested] == []


GUIDE_TOML_INCLUDES = {
    "guides/compose-a-domain/choosing-adapters.md": [
        "guides/compose-a-domain/choosing-adapters/production.toml",
    ],
    "guides/compose-a-domain/production-configuration.md": [
        "guides/compose-a-domain/production-configuration/elasticsearch.toml",
        "guides/compose-a-domain/production-configuration/multiple_databases.toml",
    ],
    "guides/multi-domain-applications.md": [
        "guides/multi-domain-applications/catalogue.toml",
    ],
    "patterns/eventual-consistency-in-uis.md": [
        "patterns/eventual-consistency-in-uis/sync.toml",
    ],
    "patterns/publishing-events-to-external-brokers.md": [
        "patterns/publishing-events-to-external-brokers/partner_broker.toml",
        "patterns/publishing-events-to-external-brokers/two_external_brokers.toml",
    ],
}


@pytest.mark.parametrize("page", sorted(GUIDE_TOML_INCLUDES))
def test_guide_page_includes_the_toml_files_its_tests_load(page: str):
    included = toml_includes((DOCS / page).read_text(encoding="utf-8"))
    expected = GUIDE_TOML_INCLUDES[page]

    assert [path for path in expected if not (DOCS_SRC / path).is_file()] == []
    assert [path for path in expected if path not in included] == []


def test_toml_includes_lists_the_included_paths():
    source = (
        '```toml\n--8<-- "adapters/x/domain.toml"\n```\n'
        '```toml\n# fragment\n--8<-- "adapters/x/skipped.toml"\n```\n'
        '```toml\n--8<-- "adapters/x/001.py"\n```\n'
    )

    assert toml_includes(source) == ["adapters/x/domain.toml"]
