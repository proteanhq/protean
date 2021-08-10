from datetime import datetime
from enum import Enum

from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import Auto, DateTime, Dict, String
from protean.core.repository import BaseRepository
from protean.globals import current_domain


class JobStatus(Enum):
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    ERRORED = "ERRORED"
    COMPLETED = "COMPLETED"


class JobTypes(Enum):
    SUBSCRIPTION = "SUBSCRIPTION"


class Job(BaseAggregate):
    job_id = Auto(identifier=True)
    type = String(max_length=50, required=True)
    payload = Dict(required=True)
    status = String(max_length=15, choices=JobStatus, default=JobStatus.NEW.value)
    created_at = DateTime(required=True, default=datetime.utcnow)
    updated_at = DateTime(required=True, default=datetime.utcnow)
    errors = Dict()

    def touch(self):
        self.updated_at = datetime.utcnow()

    def mark_in_progress(self):
        self.status = JobStatus.IN_PROGRESS.value
        self.touch()

    def mark_errored(self):
        self.status = JobStatus.ERRORED.value
        self.touch()

    def mark_completed(self):
        self.status = JobStatus.COMPLETED.value
        self.touch()


class JobRepository(BaseRepository):
    class Meta:
        aggregate_cls = Job

    def get_most_recent_job_of_type(self, type: str) -> Job:
        job_dao = current_domain.get_dao(Job)
        return job_dao.query.filter(type=type).order_by("-created_at").all().first

    def get_all_jobs_of_type(self, type: str) -> Job:
        job_dao = current_domain.get_dao(Job)
        return job_dao.query.filter(type=type).order_by("-created_at").all().items

    def get_next_to_process(self) -> Job:
        event_dao = current_domain.get_dao(Job)
        return (
            event_dao.query.filter(status=JobStatus.NEW.value)
            .order_by("created_at")
            .all()
            .first
        )
