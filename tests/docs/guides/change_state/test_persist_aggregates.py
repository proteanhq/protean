"""Check what docs/guides/change-state/persist-aggregates.md says about saving.

Each example persists its aggregates when it loads. Each test loads its
example fresh, so every test gets its own domain and its own memory database.
"""

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_add_persists_the_person_with_the_shown_values():
    module = load_example("guides/change-state/001.py")

    with module.domain.domain_context():
        person = module.domain.repository_for(module.Person).get("1")

        assert person.to_dict() == {
            "name": "John Doe",
            "email": "john.doe@localhost",
            "id": "1",
            "_version": 0,
        }


@pytest.fixture
def versions():
    """The two equivalent ways to call `add`, run with persons 1 and 2."""
    return load_example("guides/change-state/persist-aggregates/001.py")


def test_version_1_add_without_a_unit_of_work_persists(versions):
    with versions.domain.domain_context():
        person = versions.domain.repository_for(versions.Person).get("1")

        assert person.name == "John Doe"
        assert person.email == "john.doe@localhost"


def test_version_2_add_inside_a_unit_of_work_persists(versions):
    with versions.domain.domain_context():
        person = versions.domain.repository_for(versions.Person).get("2")

        assert person.name == "Jane Doe"
        assert person.email == "jane.doe@localhost"


def test_add_persists_the_post_and_both_comments():
    module = load_example("guides/change-state/002.py")

    with module.domain.domain_context():
        post = module.domain.repository_for(module.Post).get("1")

        assert post.title == "A Great Post"
        assert post.body == "This is the body of a great post"
        comments = sorted(post.comments, key=lambda comment: comment.id)
        assert [(c.id, c.content, c.rating) for c in comments] == [
            ("1", "Amazing!", 5.0),
            ("2", "Great!", 4.5),
        ]


@pytest.fixture
def events():
    """The `Post` that raises `PostPublished` when published."""
    module = load_example("guides/change-state/003.py")
    module.domain.init(traverse=False)
    return module


def test_publish_raises_post_published(events):
    with events.domain.domain_context():
        post = events.Post(title="Events in Aggregates", body="Lorem ipsum")
        post.publish()

        assert post.published is True
        assert len(post._events) == 1
        event = post._events[0]
        assert isinstance(event, events.PostPublished)
        assert event.post_id == post.id
        assert event.body == "Lorem ipsum"


def test_add_publishes_the_events_and_clears_them(events):
    with events.domain.domain_context():
        post = events.Post(title="Events in Aggregates", body="Lorem ipsum")
        post.publish()
        assert len(post._events) == 1

        events.domain.repository_for(events.Post).add(post)

        assert post._events == []
        stored = events.domain.event_store.store.read(
            f"{post.meta_.stream_category}-{post.id}"
        )
        assert [message.metadata.headers.type for message in stored] == [
            events.PostPublished.__type__
        ]


def test_adding_a_changed_post_again_updates_it(events):
    with events.domain.domain_context():
        repo = events.domain.repository_for(events.Post)
        post = events.Post(id="1", title="Events in Aggregates", body="Lorem ipsum")
        repo.add(post)

        post.title = "(Updated Title) Events in Entities"
        repo.add(post)

        assert repo.get("1").to_dict() == {
            "title": "(Updated Title) Events in Entities",
            "body": "Lorem ipsum",
            "published": False,
            "id": "1",
            "_version": 0,
        }
