from protean import Domain, handle, use_case
from protean.fields import Identifier, String, Text
from protean.utils.globals import current_domain

domain = Domain()


# --8<-- [start:application_service]
@domain.aggregate
class Post:
    title: String(max_length=100, required=True)
    body: Text(required=True)
    status: String(max_length=20, default="DRAFT")

    def publish(self):
        self.status = "PUBLISHED"


@domain.application_service(part_of=Post)
class PostService:
    @use_case
    def create_post(self, title: str, body: str) -> str:
        post = Post(title=title, body=body)
        current_domain.repository_for(Post).add(post)
        return post.id


# --8<-- [end:application_service]


# --8<-- [start:cqrs]
@domain.command(part_of=Post)
class PublishPost:
    post_id: Identifier(required=True)


@domain.command_handler(part_of=Post)
class PostCommandHandler:
    @handle(PublishPost)
    def publish(self, command: PublishPost):
        repo = current_domain.repository_for(Post)
        post = repo.get(command.post_id)
        post.publish()
        repo.add(post)


# --8<-- [end:cqrs]
