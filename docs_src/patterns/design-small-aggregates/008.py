from protean import Domain, handle
from protean.fields import Auto, DateTime, Float, HasMany, Identifier, String, Text
from protean.utils.globals import current_domain

domain = Domain(name="SmallAggregatesProjects")
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --8<-- [start:aggregates]
@domain.aggregate
class Project:
    project_id: Auto(identifier=True)
    name: String(required=True)
    description: Text()
    status: String(default="active")
    progress: Float(default=0.0)

    def update_progress(self, completed_count, total_count):
        if total_count > 0:
            self.progress = (completed_count / total_count) * 100


@domain.aggregate
class Team:
    team_id: Auto(identifier=True)
    project_id: Identifier(required=True)  # References Project
    members = HasMany("TeamMember")


@domain.entity(part_of=Team)
class TeamMember:
    user_id: Identifier(required=True)
    role: String(default="member")


@domain.aggregate
class Task:
    task_id: Auto(identifier=True)
    project_id: Identifier(required=True)  # References Project
    assignee_id: Identifier()  # References a User
    title: String(required=True)
    status: String(default="open")
    comments = HasMany("Comment")

    def complete(self):
        if self.status == "completed":
            return
        self.status = "completed"
        self.raise_(
            TaskCompleted(
                task_id=self.task_id,
                project_id=self.project_id,
            )
        )


@domain.event(part_of=Task)
class TaskCompleted:
    task_id: Identifier(required=True)
    project_id: Identifier(required=True)


@domain.entity(part_of=Task)
class Comment:
    author_id: Identifier(required=True)
    content: Text(required=True)
    posted_at: DateTime()


@domain.aggregate
class TimeEntry:
    entry_id: Auto(identifier=True)
    task_id: Identifier(required=True)  # References Task
    user_id: Identifier(required=True)  # References User
    hours: Float(required=True)
    description: Text()


# --8<-- [end:aggregates]


# --8<-- [start:progress_handler]
@domain.command(part_of=Project)
class RecalculateProgress:
    project_id: Identifier(required=True)


@domain.event_handler(part_of=Task)
class TaskEventHandler:
    @handle(TaskCompleted)
    def on_task_completed(self, event: TaskCompleted):
        current_domain.process(RecalculateProgress(project_id=event.project_id))


@domain.command_handler(part_of=Project)
class ProjectCommandHandler:
    @handle(RecalculateProgress)
    def recalculate_progress(self, command: RecalculateProgress):
        # `count()` issues a SELECT COUNT(*); it does not load the tasks
        tasks = current_domain.repository_for(Task).query.filter(
            project_id=command.project_id
        )
        repo = current_domain.repository_for(Project)
        project = repo.get(command.project_id)
        project.update_progress(
            tasks.filter(status="completed").count(),
            tasks.count(),
        )
        repo.add(project)


# --8<-- [end:progress_handler]
