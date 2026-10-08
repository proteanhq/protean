# --8<-- [start:full]
from protean import Domain
from protean.fields import String

domain = Domain()


@domain.aggregate
class Task:
    title: String(max_length=200, required=True)


def main():
    domain.init(traverse=False)

    with domain.domain_context():
        repo = domain.repository_for(Task)
        repo.add(Task(title="Write documentation"))


if __name__ == "__main__":
    main()
# --8<-- [end:full]
