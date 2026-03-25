import os
from uuid import uuid4
from urllib.parse import urlparse

from django.conf import settings
from django.core.files.storage import default_storage
from django.utils import timezone


ALLOWED_ILLUSTRATION_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_ILLUSTRATION_SIZE_BYTES = 5 * 1024 * 1024
EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def build_goal_illustration_storage_path(goal, uploaded_file) -> str:
    extension = EXTENSION_BY_CONTENT_TYPE.get(uploaded_file.content_type, os.path.splitext(uploaded_file.name)[1] or ".bin")
    return f"goal_illustrations/{goal.user_id}/{goal.id}/{uuid4().hex}{extension}"


def save_goal_illustration(goal, uploaded_file) -> str:
    clear_goal_illustration(goal, save=False)
    storage_path = build_goal_illustration_storage_path(goal, uploaded_file)
    saved_path = default_storage.save(storage_path, uploaded_file)
    goal.illustration_url = default_storage.url(saved_path)
    goal.illustration_status = "done"
    goal.illustration_generated_at = timezone.now()
    goal.save(update_fields=["illustration_url", "illustration_status", "illustration_generated_at", "updated_at"])
    return goal.illustration_url


def clear_goal_illustration(goal, *, save: bool = True) -> None:
    storage_path = _extract_storage_path(goal.illustration_url)

    if storage_path and default_storage.exists(storage_path):
        default_storage.delete(storage_path)

    goal.illustration_url = None
    goal.illustration_status = "pending"
    goal.illustration_generated_at = None

    if save:
        goal.save(
            update_fields=[
                "illustration_url",
                "illustration_status",
                "illustration_generated_at",
                "updated_at",
            ]
        )


def _extract_storage_path(illustration_url: str | None) -> str:
    parsed_url = urlparse(illustration_url or "")
    path = parsed_url.path or illustration_url or ""
    normalized_media_url = str(getattr(settings, "MEDIA_URL", "/media/")).strip() or "/media/"
    if path.startswith(normalized_media_url):
        path = path[len(normalized_media_url):]
    return path.lstrip("/")
