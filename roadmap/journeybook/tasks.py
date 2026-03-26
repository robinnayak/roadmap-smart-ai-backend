from __future__ import annotations

import logging

from celery import shared_task

from journeybook.models import JourneyBook

logger = logging.getLogger(__name__)


@shared_task
def generate_journey_book_task(book_id: str) -> None:
    from journeybook.views import JourneyBookViewSet

    book = (
        JourneyBook.objects.select_related("user", "goal")
        .prefetch_related("goals")
        .filter(id=book_id)
        .first()
    )
    if not book:
        logger.warning("Journey Book task skipped because book %s no longer exists.", book_id)
        return

    viewset = JourneyBookViewSet()
    logger.info("Generating Journey Book %s via Celery task.", book_id)
    data, metrics = viewset._collect_preview_metrics(book)
    viewset._generate_sync(book=book, data=data, metrics=metrics)
