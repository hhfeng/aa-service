import uuid
from typing import Any

_jobs: dict[str, dict] = {}


def create_job() -> str:
    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {"status": "pending", "result": None, "error": None}
    return job_id


def set_running(job_id: str) -> None:
    _jobs[job_id]["status"] = "running"


def set_done(job_id: str, result: Any) -> None:
    _jobs[job_id]["status"] = "done"
    _jobs[job_id]["result"] = result


def set_error(job_id: str, error: str) -> None:
    _jobs[job_id]["status"] = "error"
    _jobs[job_id]["error"] = error


def get_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)
