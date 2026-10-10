"""The pages converted to docs_src keep their code there.

On each page in ``PAGES``, a Python block either is marked ``# fragment`` or
holds nothing but named-section includes, such as
``--8<-- "guides/x/001.py:full"``. A line-range include or inline code that is
not a fragment fails the test, so a converted page cannot drift back.
"""

from __future__ import annotations

import re

import pytest

from tests.docs.support import DOCS
from tests.support.snippets import extract_blocks

pytestmark = pytest.mark.no_test_domain

PAGES = (
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
    "guides/consume-state/projections.md",
    "guides/consume-state/query-handlers.md",
    "guides/consume-state/subscribers.md",
    "guides/domain-definition/aggregates.md",
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
    "patterns/aggregate-state-machines.md",
    "patterns/creating-identities-early.md",
    "patterns/design-small-aggregates.md",
    "patterns/encapsulate-state-changes.md",
    "patterns/factory-methods-for-aggregate-creation.md",
    "patterns/one-aggregate-per-transaction.md",
    "patterns/optimistic-concurrency-as-design-tool.md",
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
)

_SECTION_INCLUDE = re.compile(r'^--8<-- "[^":]+\.py:[A-Za-z_][\w-]*"$')


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
