# Protean

**Protean** is an opinionated Python framework for building event-driven applications with Domain-Driven Design — aggregates, CQRS, and event sourcing are first-class, and your domain logic stays independent of the database, broker, and API you run it on.

[![Python](https://img.shields.io/pypi/pyversions/protean?label=Python)](https://github.com/proteanhq/protean/)
[![Release](https://img.shields.io/pypi/v/protean?label=Release&style=flat-square)](https://pypi.org/project/protean/)
[![Build Status](https://github.com/proteanhq/protean/actions/workflows/ci.yml/badge.svg)](https://github.com/proteanhq/protean/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/proteanhq/protean/graph/badge.svg?token=0sFuFdLBOx)](https://codecov.io/gh/proteanhq/protean)
[![Tests](https://img.shields.io/badge/tests-12%2C000%2B-brightgreen)](https://docs.proteanhq.com/community/quality/)
[![Maintainability](https://img.shields.io/badge/maintainability-A-brightgreen)](https://docs.proteanhq.com/community/quality/)

**🗺️ Roadmap:** [where Protean is headed next](https://github.com/proteanhq/protean/discussions/1356), and the [current milestone](https://github.com/proteanhq/protean/milestones) for the issue-by-issue detail.

## Installation

Protean is available on PyPI:

```console
$ pip install protean
```

Protean officially supports Python 3.11+.

## Quick Start

A command flows to its handler, the aggregate raises an event, an event
handler reacts, and a projector keeps a read-optimized feed in sync, all
wired by the domain, independent of infrastructure:

```python
from protean import Domain, current_domain, handle
from protean.core.projector import on
from protean.fields import Identifier, String, Text

domain = Domain()


@domain.aggregate
class Post:
    title: String(max_length=100, required=True)
    body: Text(required=True)
    status: String(max_length=20, default="DRAFT")

    def publish(self):
        self.status = "PUBLISHED"
        self.raise_(PostPublished(post_id=self.id, title=self.title))


@domain.event(part_of=Post)
class PostPublished:
    post_id: Identifier(required=True)
    title: String(required=True)


@domain.command(part_of=Post)
class PublishPost:
    title: String(max_length=100, required=True)
    body: Text(required=True)


@domain.command_handler(part_of=Post)
class PostCommandHandler:
    @handle(PublishPost)
    def publish_post(self, command: PublishPost):
        post = Post(title=command.title, body=command.body)
        post.publish()
        current_domain.repository_for(Post).add(post)
        return post.id


@domain.event_handler(part_of=Post)
class PostEventHandler:
    @handle(PostPublished)
    def announce(self, event: PostPublished):
        print(f"Event handled: post published ({event.title})")


@domain.projection
class PublishedPostsFeed:
    """A read-optimized feed of published posts."""

    post_id: Identifier(identifier=True, required=True)
    title: String(max_length=100, required=True)


@domain.projector(projector_for=PublishedPostsFeed, aggregates=[Post])
class PublishedPostsFeedProjector:
    """Maintains the PublishedPostsFeed projection from Post events."""

    @on(PostPublished)
    def on_post_published(self, event: PostPublished):
        feed_entry = PublishedPostsFeed(post_id=event.post_id, title=event.title)
        current_domain.repository_for(PublishedPostsFeed).add(feed_entry)


if __name__ == "__main__":
    domain.config["command_processing"] = "sync"
    domain.config["event_processing"] = "sync"

    domain.init(traverse=False)

    with domain.domain_context():
        # Write: publish a post through the command.
        post_id = domain.process(
            PublishPost(title="Hello, Protean!", body="My first published post.")
        )
        post = domain.repository_for(Post).get(post_id)
        print(f"Post created: {post.title} (status: {post.status})")

        # Read: the projector has already filled the feed inline.
        feed = domain.view_for(PublishedPostsFeed).query.all()
        print(f"Published posts feed: {feed.total} row(s)")
        for entry in feed.items:
            print(f"  - {entry.title}")
```

## Documentation

Online docs are available at [https://docs.proteanhq.com](https://docs.proteanhq.com).

### Versioning

Protean does not use strict semantic versioning. The promise is:
**Code that runs warning-free on 1.N runs unmodified on 1.N+1.** Every removal
is announced by a deprecation warning naming the release it lands in, at least
one release ahead, so you can turn "will this upgrade break us?" into a test run.
See the [versioning policy](https://docs.proteanhq.com/reference/versioning-policy/)
for the full contract.

## Quality

Every commit runs the in-memory core suite across 5 Python versions and all 5 backing services on the newest stable Python; the full adapter matrix across every version runs nightly.

| Metric | Value |
|---|---|
| Tests | 12,000+ ([quality report](https://docs.proteanhq.com/community/quality/)) |
| Linting | Zero violations (Ruff) |
| Complexity | Avg 3.38 cyclomatic (A grade) |
| Maintainability | A rank (95% of files) |
| CI Matrix | Python 3.11-3.14 + 3.15 prerelease; PostgreSQL, Redis, Elasticsearch, MessageDB, MSSQL on the newest stable per PR, full matrix nightly |

See the full [Quality Report](https://docs.proteanhq.com/community/quality/) for details.

## Contributing

> **Note**: Protean framework is not associated or related to [Protean eGov Technologies](https://www.proteantech.in/) or [Code for Gov Tech](https://codeforgovtech.in/) initiatives.

Protean is developed and maintained by a single maintainer. The contributions
that help most are **bug reports**, **real-world use cases**, and **adapter
packages** built against the public conformance suite.

- Found a bug or have a use case to share? [Open an issue](https://github.com/proteanhq/protean/issues). Clear, reproducible reports are the most valuable contribution you can make, and they are answered as a priority.
- Planning a non-trivial code change? Open an issue to discuss it first, before investing in a pull request. Unsolicited large PRs may not be merged. Small, obvious fixes are welcome directly.
- Building an adapter? Adapters live in their own packages, certified against the conformance suite. See the [contributing guide](https://docs.proteanhq.com/community/contributing/setup/).

See [CONTRIBUTING.md](CONTRIBUTING.md) and the
[community](https://docs.proteanhq.com/community/) section for the full picture.

## License

Protean is licensed under the [Apache License 2.0](LICENSE).

**Licensing commitment.** The Protean framework core is, and will remain,
available under the Apache License 2.0. This is a permanent commitment: the
core will not be relicensed to a proprietary or source-available license.

Copyright 2018-2026 Subhash Bhushan C and the Protean contributors.
