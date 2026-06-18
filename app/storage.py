import os
import uuid

from app.config import settings


def ensure_upload_dir() -> str:
    os.makedirs(settings.upload_dir, exist_ok=True)
    return settings.upload_dir


def upload_path(job_id: uuid.UUID) -> str:
    return os.path.join(settings.upload_dir, f"{job_id}.csv")


def save_upload(job_id: uuid.UUID, content: bytes) -> str:
    """Write uploaded bytes to the shared volume; return the stored path."""
    ensure_upload_dir()
    path = upload_path(job_id)
    with open(path, "wb") as f:
        f.write(content)
    return path


def read_upload(path: str) -> str:
    """Read a stored CSV file as text (utf-8, tolerant of BOM)."""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return f.read()
