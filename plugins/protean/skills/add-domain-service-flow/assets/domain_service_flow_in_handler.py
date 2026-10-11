"""
Domain service wired through a command handler.

This example demonstrates:
- Domain service called from within a command handler
- The service validates both aggregates but changes only Course
- The handler loads both aggregates, runs the service, and persists only Course
- Course raises StudentEnrolled; an event handler in Course's cluster issues
  AssignCourse, and Student's command handler applies it
- Both aggregates keep a list of what they have applied, so a repeated
  EnrollStudent takes no second seat and a late StudentEnrolled changes nothing
- Full flow: Command → Handler → Domain Service → Persist Course → Event →
  Command → Persist Student

Domain: A course enrollment system where enrolling a student requires checking
both course capacity and student eligibility. The EnrollStudentService checks
both aggregates in one step and changes the Course. The Student is updated in
its own transaction afterwards, so it is eventually consistent with the Course.

Processing is synchronous, so one EnrollStudent command runs the whole flow
in-process, with no broker and no server. A deployed domain leaves both
asynchronous and lets the server deliver the event and the command.

Usage:
    from domain_service_flow_in_handler import Course, EnrollStudent, Student, domain

    domain.init(traverse=False)
    with domain.domain_context():
        domain.repository_for(Course).add(
            Course(course_id="C-1", title="Algebra", capacity=30)
        )
        domain.repository_for(Student).add(Student(student_id="S-1", name="Ann"))

        domain.process(EnrollStudent(course_id="C-1", student_id="S-1"))
        # Course C-1 lists S-1, and S-1 lists C-1.
"""

from protean import Domain, current_domain, handle, invariant
from protean.exceptions import ValidationError
from protean.fields import Identifier, Integer, List, String

domain = Domain(__name__)

# Run the whole flow in-process: StudentEnrolled reaches the event handler when
# the unit of work that saves the course commits, and AssignCourse reaches its
# handler as soon as it is issued.
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --- Events ---


@domain.event(part_of="Course")
class StudentEnrolled:
    """Raised when a course accepts a student."""

    course_id: Identifier(required=True)
    student_id: Identifier(required=True)


# --- Aggregates ---


@domain.aggregate
class Course:
    """Course aggregate with enrollment capacity.

    `student_ids` lists the enrolled students. Its length is the number of
    seats taken, and the command handler checks it so that a repeated
    EnrollStudent takes no second seat.
    """

    course_id: Identifier(identifier=True)
    title: String(required=True, max_length=200)
    capacity: Integer(required=True)
    student_ids: List(content_type=String)

    def enroll(self, student_id):
        """Take one seat for the student and announce it."""
        self.student_ids = [*self.student_ids, student_id]
        self.raise_(StudentEnrolled(course_id=self.course_id, student_id=student_id))


@domain.aggregate
class Student:
    """Student aggregate with enrollment status.

    `course_ids` lists the courses this student is enrolled in. The
    AssignCourse handler skips a course that is already listed, so a
    StudentEnrolled delivered twice, or late after another enrollment, leaves
    the list as it is.
    """

    student_id: Identifier(identifier=True)
    name: String(required=True, max_length=100)
    status: String(default="active")
    course_ids: List(content_type=String)

    def assign_course(self, course_id):
        """Add a course to this student's courses."""
        self.course_ids = [*self.course_ids, course_id]


# --- Domain Service ---


@domain.domain_service(part_of=[Course, Student])
class EnrollStudentService:
    """Enroll a student in a course.

    Validates:
    - Course has available capacity
    - Student is active (not suspended)

    Changes:
    - The student added to Course.student_ids, and StudentEnrolled raised

    StudentEnrolled carries the change to the Student, in its own transaction.
    """

    def __init__(self, course, student):
        self.course = course
        self.student = student

    @invariant.pre
    def course_must_have_capacity(self):
        """Course must have available seats."""
        if len(self.course.student_ids) >= self.course.capacity:
            raise ValidationError({"_service": ["Course is at full capacity"]})

    @invariant.pre
    def student_must_be_active(self):
        """Student must be in active status."""
        if self.student.status != "active":
            raise ValidationError({"_service": ["Only active students can enroll"]})

    def __call__(self):
        """Execute enrollment on the Course."""
        self.course.enroll(self.student.student_id)


# --- Commands ---


@domain.command(part_of="Course")
class EnrollStudent:
    """Command to enroll a student in a course."""

    course_id: Identifier(required=True)
    student_id: Identifier(required=True)


@domain.command(part_of="Student")
class AssignCourse:
    """Command to record a student's course on the Student."""

    student_id: Identifier(required=True)
    course_id: Identifier(required=True)


# --- Command Handlers ---


@domain.command_handler(part_of=Course)
class CourseCommandHandler:
    """Handles course-related commands."""

    @handle(EnrollStudent)
    def handle_enroll(self, command: EnrollStudent):
        """Load both aggregates, run the domain service, persist the Course."""
        course_repo = current_domain.repository_for(Course)
        course = course_repo.get(command.course_id)
        if command.student_id in course.student_ids:
            # Already enrolled. Enrolling again would take a second seat.
            return
        student = current_domain.repository_for(Student).get(command.student_id)

        # Run domain service (validates both, changes the Course)
        EnrollStudentService(course, student)()

        # Persist only the aggregate the service changed
        course_repo.add(course)


@domain.command_handler(part_of=Student)
class StudentCommandHandler:
    """Handles student-related commands."""

    @handle(AssignCourse)
    def handle_assign(self, command: AssignCourse):
        """Record the course on the Student, once."""
        repo = current_domain.repository_for(Student)
        student = repo.get(command.student_id)
        if command.course_id in student.course_ids:
            # Already applied. A redelivered StudentEnrolled reissues
            # AssignCourse, and there is nothing left to change.
            return
        student.assign_course(command.course_id)
        repo.add(student)


# --- The cross-aggregate link: an event handler in Course's cluster ---


@domain.event_handler(part_of=Course)
class AssignEnrolledStudent:
    """React to Course's own StudentEnrolled event and update the Student.

    The handler sits in Course's cluster, which owns StudentEnrolled. It hands
    off to Student with a command, and Student's command handler does the write.
    """

    @handle(StudentEnrolled)
    def on_student_enrolled(self, event: StudentEnrolled):
        current_domain.process(
            AssignCourse(student_id=event.student_id, course_id=event.course_id)
        )
