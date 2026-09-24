"""
Domain service wired through a command handler.

This example demonstrates:
- Domain service called from within a command handler
- Handler loads aggregates, runs service, persists results
- Command carries the intent, service executes the logic
- Full flow: Command → Handler → Domain Service → Persist

Domain: A course enrollment system where enrolling a student
requires checking both course capacity and student eligibility.
The EnrollStudentService validates and mutates both aggregates.
"""

from protean import Domain, handle, invariant
from protean.core.domain_service import BaseDomainService
from protean.exceptions import ValidationError
from protean.fields import Identifier, Integer, String

domain = Domain(__name__)


# --- Aggregates ---


@domain.aggregate
class Course:
    """Course aggregate with enrollment capacity."""

    course_id: Identifier(identifier=True)
    title: String(required=True, max_length=200)
    capacity: Integer(required=True)
    enrolled_count: Integer(default=0)

    def enroll_one(self):
        """Increment enrollment count."""
        self.enrolled_count += 1


@domain.aggregate
class Student:
    """Student aggregate with enrollment status."""

    student_id: Identifier(identifier=True)
    name: String(required=True, max_length=100)
    status: String(default="active")
    enrolled_course_id: Identifier()

    def assign_course(self, course_id):
        """Assign a course to this student."""
        self.enrolled_course_id = course_id


# --- Domain Service ---


@domain.domain_service(part_of=[Course, Student])
class EnrollStudentService:
    """Enroll a student in a course.

    Validates:
    - Course has available capacity
    - Student is active (not suspended)

    Mutates:
    - Course.enrolled_count incremented
    - Student.enrolled_course_id set
    """

    def __init__(self, course, student):
        BaseDomainService.__init__(self, *(course, student))
        self.course = course
        self.student = student

    @invariant.pre
    def course_must_have_capacity(self):
        """Course must have available seats."""
        if self.course.enrolled_count >= self.course.capacity:
            raise ValidationError({"_service": ["Course is at full capacity"]})

    @invariant.pre
    def student_must_be_active(self):
        """Student must be in active status."""
        if self.student.status != "active":
            raise ValidationError({"_service": ["Only active students can enroll"]})

    def __call__(self):
        """Execute enrollment: update both aggregates."""
        self.course.enroll_one()
        self.student.assign_course(self.course.course_id)


# --- Command ---


@domain.command(part_of="Course")
class EnrollStudent:
    """Command to enroll a student in a course."""

    course_id: Identifier(required=True)
    student_id: Identifier(required=True)


# --- Command Handler ---


@domain.command_handler(part_of=Course)
class CourseCommandHandler:
    """Handles course-related commands."""

    @handle(EnrollStudent)
    def handle_enroll(self, command: EnrollStudent):
        """Load aggregates, run domain service, persist."""
        course = domain.repository_for(Course).get(command.course_id)
        student = domain.repository_for(Student).get(command.student_id)

        # Run domain service (validates and mutates)
        EnrollStudentService(course, student)()

        # Handler is responsible for persisting
        domain.repository_for(Course).add(course)
        domain.repository_for(Student).add(student)
