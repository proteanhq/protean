"""
Command handler that creates a brand new aggregate instance.

This example demonstrates:
- Creating a new aggregate (vs. loading an existing one from repository)
- Handler that constructs an aggregate from command data
- Returning values from handler methods (synchronous processing)
- The distinction between "create" handlers and "update" handlers

Usage:
    command = CreateProject(
        project_id="PRJ-001",
        name="Website Redesign",
        owner_id="USR-001",
    )
    result = domain.process(command, asynchronous=False)
"""

from protean import Domain, handle
from protean.fields import Identifier, String

# Domain setup
domain = Domain()


@domain.aggregate
class Project:
    """Project aggregate for task management."""

    project_id: Identifier(identifier=True)
    name: String(required=True, max_length=200)
    description: String(max_length=2000)
    owner_id: String(required=True)
    status: String(default="active")

    def rename(self, new_name: str):
        """Rename the project."""
        if not new_name or not new_name.strip():
            raise ValueError("Project name cannot be empty")
        self.name = new_name.strip()

    def close(self):
        """Close the project."""
        if self.status == "closed":
            raise ValueError("Project is already closed")
        self.status = "closed"


@domain.command(part_of="Project")
class CreateProject:
    """Command to create a new project."""

    project_id: Identifier(required=True)
    name: String(required=True, max_length=200)
    description: String(max_length=2000)
    owner_id: String(required=True)


@domain.command(part_of="Project")
class RenameProject:
    """Command to rename an existing project."""

    project_id: Identifier(required=True)
    new_name: String(required=True, max_length=200)


@domain.command(part_of="Project")
class CloseProject:
    """Command to close a project."""

    project_id: Identifier(required=True)


@domain.command_handler(part_of=Project)
class ProjectCommandHandler:
    """Handler for project commands.

    Demonstrates both creating new aggregates and loading existing ones.
    - CreateProject: constructs a brand new Project aggregate
    - RenameProject: loads an existing Project from the repository
    - CloseProject: loads an existing Project from the repository
    """

    @handle(CreateProject)
    def handle_create(self, command: CreateProject):
        """Handle CreateProject by constructing a new aggregate.

        This handler creates the aggregate directly from command data.
        No repository load is needed since the aggregate doesn't exist yet.
        """
        project = Project(
            project_id=command.project_id,
            name=command.name,
            description=command.description,
            owner_id=command.owner_id,
        )
        domain.repository_for(Project).add(project)
        return project.project_id

    @handle(RenameProject)
    def handle_rename(self, command: RenameProject):
        """Handle RenameProject by loading and modifying an existing aggregate."""
        project = domain.repository_for(Project).get(command.project_id)
        project.rename(new_name=command.new_name)
        domain.repository_for(Project).add(project)

    @handle(CloseProject)
    def handle_close(self, command: CloseProject):
        """Handle CloseProject by loading and closing an existing aggregate."""
        project = domain.repository_for(Project).get(command.project_id)
        project.close()
        domain.repository_for(Project).add(project)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create a new project
        create_cmd = CreateProject(
            project_id="PRJ-001",
            name="Website Redesign",
            description="Complete redesign of the company website",
            owner_id="USR-001",
        )
        result = domain.process(create_cmd, asynchronous=False)
        print(f"Created project: {result}")

        # Rename the project
        rename_cmd = RenameProject(
            project_id="PRJ-001",
            new_name="Website Redesign v2",
        )
        domain.process(rename_cmd, asynchronous=False)
        print("Project renamed")

        # Close the project
        close_cmd = CloseProject(project_id="PRJ-001")
        domain.process(close_cmd, asynchronous=False)
        print("Project closed")
