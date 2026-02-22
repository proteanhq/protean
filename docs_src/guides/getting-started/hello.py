from protean import Domain
from protean.fields import Boolean, String

domain = Domain()


@domain.aggregate
class Task:
    title: String(max_length=100, required=True)
    done: Boolean(default=False)


domain.init(traverse=False)

if __name__ == "__main__":
    with domain.domain_context():
        # Create
        task = Task(title="Buy groceries")
        print(f"Created: {task.title} (done={task.done})")

        # Save
        repo = domain.repository_for(Task)
        repo.add(task)

        # Load
        saved = repo.get(task.id)
        print(f"Loaded:  {saved.title} (done={saved.done})")
        print(f"ID:      {saved.id}")
