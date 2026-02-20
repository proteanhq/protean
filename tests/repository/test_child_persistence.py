import pytest

from protean.utils.globals import current_domain

from .child_entities import Comment, Member, Post, PostMeta, Team


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Post)
    test_domain.register(PostMeta, part_of=Post)
    test_domain.register(Comment, part_of=Post)
    test_domain.register(Team)
    test_domain.register(Member, part_of=Team)
    test_domain.init(traverse=False)


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestHasOnePersistence:
    @pytest.fixture
    def persisted_post(self, test_domain):
        return test_domain.repository_for(Post).add(
            Post(title="Test Post", slug="test-post", content="Do Re Mi Fa")
        )

    def test_that_has_one_entity_can_be_added(self, persisted_post):
        post_repo = current_domain.repository_for(Post)

        meta = PostMeta(likes=1)
        persisted_post.post_meta = meta

        post_repo.add(persisted_post)

        refreshed_post = post_repo.get(persisted_post.id)
        assert refreshed_post is not None
        assert refreshed_post.post_meta is not None
        assert isinstance(refreshed_post.post_meta, PostMeta)
        assert refreshed_post.post_meta == meta

    def test_that_adding_another_has_one_entity_replaces_existing_child(
        self, persisted_post
    ):
        post_repo = current_domain.repository_for(Post)

        meta1 = PostMeta(likes=1)
        meta2 = PostMeta(likes=2)
        persisted_post.post_meta = meta1

        post_repo.add(persisted_post)

        post_to_alter = post_repo.get(persisted_post.id)
        post_to_alter.post_meta = meta2

        post_repo.add(post_to_alter)

        refreshed_post = post_repo.get(persisted_post.id)

        assert refreshed_post is not None
        assert refreshed_post.post_meta is not None
        assert isinstance(refreshed_post.post_meta, PostMeta)
        assert refreshed_post.post_meta == meta2

    def test_that_a_has_one_entity_can_be_removed(self, persisted_post):
        post_repo = current_domain.repository_for(Post)

        meta = PostMeta(likes=1)
        persisted_post.post_meta = meta

        post_repo.add(persisted_post)

        post_to_alter = post_repo.get(persisted_post.id)
        post_to_alter.post_meta = None

        post_repo.add(post_to_alter)

        refreshed_post = post_repo.get(persisted_post.id)
        assert refreshed_post is not None
        assert refreshed_post.post_meta is None


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestHasManyPersistence:
    @pytest.fixture
    def persisted_post(self, test_domain):
        post = test_domain.repository_for(Post).add(
            Post(title="Test Post", slug="test-post", content="Do Re Mi Fa")
        )
        return post

    def test_that_a_has_many_entity_can_be_added(self, persisted_post):
        post_repo = current_domain.repository_for(Post)

        comment = Comment(content="So La Ti Do")
        persisted_post.add_comments(comment)

        post_repo.add(persisted_post)

        refreshed_post = post_repo.get(persisted_post.id)
        assert refreshed_post is not None
        assert refreshed_post.comments is not None
        assert comment.id in [comment.id for comment in refreshed_post.comments]

    def test_that_multiple_has_many_entities_can_be_added(self, persisted_post):
        post_repo = current_domain.repository_for(Post)

        comment1 = Comment(content="So La Ti Do")
        comment2 = Comment(content="Do Re Mi Fa")
        persisted_post.add_comments(comment1)
        persisted_post.add_comments(comment2)

        post_repo.add(persisted_post)

        refreshed_post = post_repo.get(persisted_post.id)
        assert refreshed_post is not None
        assert refreshed_post.comments is not None
        assert len(refreshed_post.comments) == 2
        assert all(
            comment in [comment for comment in refreshed_post.comments]
            for comment in [comment1, comment2]
        )

    def test_that_a_has_many_entity_can_be_removed(self, persisted_post):
        post_repo = current_domain.repository_for(Post)

        comment = Comment(content="So La Ti Do")
        persisted_post.add_comments(comment)

        post_repo.add(persisted_post)

        post_to_alter = post_repo.get(persisted_post.id)
        post_to_alter.remove_comments(comment)

        post_repo.add(post_to_alter)

        refreshed_post = post_repo.get(persisted_post.id)
        assert refreshed_post is not None
        assert refreshed_post.comments is not None
        assert len(refreshed_post.comments) == 0

    def test_that_a_has_many_entity_can_be_removed_from_among_many(
        self, persisted_post
    ):
        post_repo = current_domain.repository_for(Post)

        comment1 = Comment(content="So La Ti Do")
        comment2 = Comment(content="Do Re Mi Fa")
        persisted_post.add_comments(comment1)
        persisted_post.add_comments(comment2)

        post_repo.add(persisted_post)

        post_to_alter = post_repo.get(persisted_post.id)
        post_to_alter.remove_comments(comment1)

        post_repo.add(post_to_alter)

        refreshed_post = post_repo.get(persisted_post.id)
        assert refreshed_post is not None
        assert refreshed_post.comments is not None
        assert len(refreshed_post.comments) == 1
        assert comment2.id in [comment.id for comment in refreshed_post.comments]


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestHasManyFetchObjectsState:
    """Tests that HasMany._fetch_objects() does not mark loaded children as
    changed.  Without the fix, setattr(item, key, value) in _fetch_objects
    triggered __setattr__'s shadow field path which called mark_changed(),
    making freshly-loaded children appear dirty."""

    @pytest.fixture
    def team_with_members(self, test_domain):
        """Create a team with two members, persist, and return the team id."""
        team = Team(name="Alpha")
        m1 = Member(name="Alice", score=10)
        m2 = Member(name="Bob", score=20)
        team.add_members(m1)
        team.add_members(m2)
        test_domain.repository_for(Team).add(team)
        return team.id

    def test_fetched_children_not_marked_changed(self, test_domain, team_with_members):
        """Children loaded via HasMany lazy fetch should NOT have
        is_changed=True."""
        team = test_domain.repository_for(Team).get(team_with_members)
        members = team.members
        assert len(members) == 2

        for member in members:
            assert not member.state_.is_changed, (
                f"Member {member.name} should not be marked as changed after loading"
            )

    def test_fetched_children_are_persisted(self, test_domain, team_with_members):
        """Loaded children should have is_persisted=True (not new)."""
        team = test_domain.repository_for(Team).get(team_with_members)
        members = team.members

        for member in members:
            assert member.state_.is_persisted

    def test_fetched_children_fk_is_set(self, test_domain, team_with_members):
        """FK value should be correctly set on loaded children."""
        team = test_domain.repository_for(Team).get(team_with_members)
        members = team.members

        for member in members:
            assert member.team_id == team_with_members

    def test_direct_child_update_not_overwritten_by_sync(
        self, test_domain, team_with_members
    ):
        """A direct update to a child via its own repository should NOT be
        overwritten when the parent is re-persisted."""
        member_repo = current_domain.repository_for(Member)
        team_repo = current_domain.repository_for(Team)

        team = team_repo.get(team_with_members)
        members = team.members
        target = [m for m in members if m.name == "Alice"][0]

        target.score = 99
        member_repo.add(target)

        refreshed_member = member_repo._dao.query.filter(id=target.id).all().items[0]
        assert refreshed_member.score == 99

        team2 = team_repo.get(team_with_members)
        team_repo.add(team2)

        final_member = member_repo._dao.query.filter(id=target.id).all().items[0]
        assert final_member.score == 99, (
            "Child update was overwritten by _sync_children because "
            "fetched children were erroneously marked as changed"
        )

    def test_modifying_loaded_child_marks_it_changed(
        self, test_domain, team_with_members
    ):
        """After loading, if we explicitly modify a child, it SHOULD be
        marked as changed."""
        team = test_domain.repository_for(Team).get(team_with_members)
        member = team.members[0]
        assert not member.state_.is_changed

        member.score = 42
        assert member.state_.is_changed

    def test_adding_new_child_after_load_does_not_affect_existing(
        self, test_domain, team_with_members
    ):
        """Adding a new child to a loaded parent should not affect the
        state of already-loaded children."""
        team = test_domain.repository_for(Team).get(team_with_members)
        existing = team.members

        for member in existing:
            assert not member.state_.is_changed

        new_member = Member(name="Charlie", score=30)
        team.add_members(new_member)

        for member in existing:
            assert not member.state_.is_changed
