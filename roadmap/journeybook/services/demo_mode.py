from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any

from django.conf import settings

from journeybook.models import JourneyBook
from journeybook.services.ai_generator import AIGenerator, ChapterFallbacks, MotivationalFallbacks
from journeybook.services.metrics_calculator import MetricsCalculator
from journeybook.services.pdf_builder import PDFBuilder
from journeybook.services.print_spec import get_print_spec, normalize_trim_size

try:
    from journey_book.demo_data import get_demo_journey_data
except ModuleNotFoundError:  # pragma: no cover
    import importlib.util
    from pathlib import Path

    module_path = Path(__file__).resolve().parents[3] / "journey_book" / "demo_data.py"
    spec = importlib.util.spec_from_file_location("journey_book.demo_data", module_path)
    module = importlib.util.module_from_spec(spec) if spec else None
    if spec and module and spec.loader:
        spec.loader.exec_module(module)
        get_demo_journey_data = module.get_demo_journey_data
    else:
        raise


def _normalize_book_type(book_type: str | None) -> str:
    if book_type in {JourneyBook.BOOK_TYPE_COMPLETE, JourneyBook.BOOK_TYPE_IN_PROGRESS}:
        return book_type
    return JourneyBook.BOOK_TYPE_COMPLETE


def _structure_for(book_type: str) -> dict[str, Any]:
    if book_type == JourneyBook.BOOK_TYPE_COMPLETE:
        return {
            "chapters": [
                {"id": "ch1", "title": "Who I Was - Day One", "is_projection": False},
                {"id": "ch2", "title": "The First 30 Days", "is_projection": False},
                {"id": "ch3", "title": "The Dip", "is_projection": False},
                {"id": "ch4", "title": "The Turning Point", "is_projection": False},
                {"id": "ch5", "title": "The Progress", "is_projection": False},
                {"id": "ch6", "title": "The Moments", "is_projection": False},
                {"id": "ch7", "title": "Who I Became", "is_projection": False},
            ],
            "motivational_pages": [
                "the_day_you_didnt_quit",
                "before_after",
                "streak_heatmap",
                "invisible_wins",
                "what_you_learned",
                "three_hardest_days",
                "milestones_map",
                "letter_to_past_self",
            ],
        }

    return {
        "chapters": [
            {"id": "ch1", "title": "Who I Was - Day One", "is_projection": False},
            {"id": "ch2", "title": "Your Journey So Far", "is_projection": False},
            {"id": "ch3", "title": "The Challenges", "is_projection": False},
            {"id": "ch4", "title": "If You Keep Going", "is_projection": True},
            {"id": "ch5", "title": "The Future You", "is_projection": True},
        ],
        "motivational_pages": [
            "the_day_you_didnt_quit",
            "streak_heatmap",
            "invisible_wins",
            "what_you_learned",
            "letter_to_past_self",
        ],
    }


def _build_demo_metrics(demo_data: dict[str, Any]) -> dict[str, Any]:
    collector_like = {
        "profile": demo_data.get("profile") or {},
        "goal": demo_data.get("goal") or {},
        "journals": demo_data.get("journals") or [],
        "streaks": demo_data.get("streaks") or {},
        "word_frequencies": demo_data.get("word_frequencies") or {},
    }
    metrics = MetricsCalculator(collector_like).calculate_all()
    metrics["profile"] = collector_like["profile"]
    metrics["goal"] = collector_like["goal"]
    metrics["streaks"] = collector_like["streaks"]
    metrics["word_frequencies"] = collector_like["word_frequencies"]
    if demo_data.get("derived_milestones"):
        metrics["derived_milestones"] = demo_data["derived_milestones"]
    return metrics


def _chapter_generation_source(text: str, chapter_id: str, metrics: dict[str, Any], book_type: str) -> str:
    fallback = ChapterFallbacks.get(chapter_id, metrics, book_type)
    return "fallback" if (text or "").strip() == (fallback or "").strip() else "ai"


def _motivation_generation_source(text: str, page_type: str, metrics: dict[str, Any]) -> str:
    fallback = MotivationalFallbacks.get(page_type, metrics)
    return "fallback" if (text or "").strip() == (fallback or "").strip() else "ai"


def _summary_source(ai_count: int, fallback_count: int) -> str:
    if ai_count and fallback_count:
        return "mixed"
    if ai_count:
        return "ai"
    return "fallback"


def _demo_artifact_paths(book_type: str | None, trim_size: str | None) -> tuple[str, str, Path, Path]:
    normalized_book_type = _normalize_book_type(book_type)
    normalized_trim = normalize_trim_size(trim_size)
    filename_trim = normalized_trim.replace(".", "_")
    demo_dir = Path(settings.MEDIA_ROOT) / "journey_books" / "demo"
    return (
        normalized_book_type,
        normalized_trim,
        demo_dir / f"journey_book_demo_{normalized_book_type}_{filename_trim}.json",
        demo_dir / f"journey_book_demo_{normalized_book_type}_{filename_trim}.pdf",
    )


def _read_cached_payload(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _build_pdf_bytes_from_payload(payload: dict[str, Any]) -> BytesIO:
    demo_data = get_demo_journey_data()
    metrics = _build_demo_metrics(demo_data)
    chapter_texts = [chapter["content"] for chapter in payload["chapters"]]
    motivational_texts = [page["content"] for page in payload["motivational_pages"]]

    pdf_builder = PDFBuilder(
        user_data=demo_data,
        metrics=metrics,
        book_type=payload["book_type"],
        trim_size=payload["print_spec"]["trim_size"],
    )
    return pdf_builder.build(chapter_texts, motivational_texts, {})


def build_demo_book_payload(book_type: str | None, trim_size: str | None = None) -> dict[str, Any]:
    normalized_book_type = _normalize_book_type(book_type)
    normalized_trim = normalize_trim_size(trim_size)
    print_spec = get_print_spec(normalized_trim)

    demo_data = get_demo_journey_data()
    metrics = _build_demo_metrics(demo_data)
    structure = _structure_for(normalized_book_type)
    ai_generator = AIGenerator()

    chapters: list[dict[str, Any]] = []
    chapter_ai = 0
    chapter_fallback = 0
    for index, chapter_cfg in enumerate(structure["chapters"], start=1):
        chapter_text = ai_generator.generate_chapter(chapter_cfg, metrics, normalized_book_type)
        source = _chapter_generation_source(
            chapter_text,
            chapter_cfg.get("id", f"ch{index}"),
            metrics,
            normalized_book_type,
        )
        if source == "ai":
            chapter_ai += 1
        else:
            chapter_fallback += 1
        chapters.append(
            {
                "chapter_number": index,
                "chapter_id": chapter_cfg.get("id", f"ch{index}"),
                "chapter_title": chapter_cfg.get("title", f"Chapter {index}"),
                "is_projection": bool(chapter_cfg.get("is_projection", False)),
                "generation_source": source,
                "content": chapter_text,
                "word_count": len((chapter_text or "").split()),
            }
        )

    motivational_pages: list[dict[str, str]] = []
    motivation_ai = 0
    motivation_fallback = 0
    for page_type in structure["motivational_pages"]:
        page_text = ai_generator.generate_motivational_page(page_type, metrics)
        source = _motivation_generation_source(page_text, page_type, metrics)
        if source == "ai":
            motivation_ai += 1
        else:
            motivation_fallback += 1
        motivational_pages.append(
            {
                "page_type": page_type,
                "generation_source": source,
                "content": page_text,
            }
        )

    journey_overview = metrics.get("journey_overview") or {}
    total_entries = int(journey_overview.get("total_entries") or len(demo_data.get("journals") or []))
    longest_streak = int((metrics.get("streaks") or {}).get("longest_streak") or 0)
    days_of_data = int(journey_overview.get("days_of_data") or total_entries)
    if days_of_data <= 0 and total_entries > 0:
        days_of_data = total_entries

    return {
        "mode": "demo",
        "book_type": normalized_book_type,
        "source": "demo_data",
        "generation_source": {
            "overall": _summary_source(chapter_ai + motivation_ai, chapter_fallback + motivation_fallback),
            "chapters": _summary_source(chapter_ai, chapter_fallback),
            "motivational_pages": _summary_source(motivation_ai, motivation_fallback),
            "counts": {
                "chapters_ai": chapter_ai,
                "chapters_fallback": chapter_fallback,
                "motivational_ai": motivation_ai,
                "motivational_fallback": motivation_fallback,
            },
        },
        "print_spec": print_spec,
        "chapters": chapters,
        "motivational_pages": motivational_pages,
        "stats": {
            "days_of_data": days_of_data,
            "total_entries": total_entries,
            "longest_streak": longest_streak,
        },
    }


def get_or_create_demo_book_payload(book_type: str | None, trim_size: str | None = None) -> dict[str, Any]:
    normalized_book_type, normalized_trim, payload_path, _pdf_path = _demo_artifact_paths(
        book_type,
        trim_size,
    )
    cached_payload = _read_cached_payload(payload_path)
    if cached_payload:
        return cached_payload

    payload = build_demo_book_payload(book_type=normalized_book_type, trim_size=normalized_trim)
    _write_json(payload_path, payload)
    return payload


def build_demo_pdf_bytes(
    book_type: str | None,
    trim_size: str | None = None,
):
    payload = build_demo_book_payload(book_type=book_type, trim_size=trim_size)
    demo_data = get_demo_journey_data()
    metrics = _build_demo_metrics(demo_data)

    chapter_texts = [chapter["content"] for chapter in payload["chapters"]]
    motivational_texts = [page["content"] for page in payload["motivational_pages"]]

    pdf_builder = PDFBuilder(
        user_data=demo_data,
        metrics=metrics,
        book_type=payload["book_type"],
        trim_size=payload["print_spec"]["trim_size"],
    )
    pdf_bytes = pdf_builder.build(chapter_texts, motivational_texts, {})
    return pdf_bytes, payload


def get_or_create_demo_pdf_bytes(
    book_type: str | None,
    trim_size: str | None = None,
):
    normalized_book_type, normalized_trim, payload_path, pdf_path = _demo_artifact_paths(
        book_type,
        trim_size,
    )

    payload = _read_cached_payload(payload_path)
    if not payload:
        payload = build_demo_book_payload(book_type=normalized_book_type, trim_size=normalized_trim)
        _write_json(payload_path, payload)

    try:
        cached_pdf = pdf_path.read_bytes()
    except FileNotFoundError:
        cached_pdf = None
    except OSError:
        cached_pdf = None

    if cached_pdf is not None:
        return BytesIO(cached_pdf), payload

    pdf_bytes = _build_pdf_bytes_from_payload(payload)
    _write_bytes(pdf_path, pdf_bytes.getvalue())
    pdf_bytes.seek(0)
    return pdf_bytes, payload
