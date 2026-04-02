from __future__ import annotations

import json
import sys
from pathlib import Path

ROADMAP_ROOT = Path(__file__).resolve().parents[2]
if str(ROADMAP_ROOT) not in sys.path:
    sys.path.append(str(ROADMAP_ROOT))

try:
    from gie.exceptions import GIEServiceError
except ModuleNotFoundError:
    from roadmap.gie.exceptions import GIEServiceError


PROMPTS_DIR = Path(__file__).resolve().parents[2] / "ai" / "prompts" / "gie"
CATEGORY_LABELS = {
    "wellness": "Wellness",
    "fitness": "Fitness",
    "learning": "Learning",
}
DEFAULT_TOTAL_QUESTIONS = 5


def classify_and_generate_first_question(
    goal_text: str,
    *,
    target_slot_key: str | None = None,
    target_slot_label: str | None = None,
    target_slot_description: str | None = None,
):
    def _load_prompt(relative_path: str) -> str:
        path = PROMPTS_DIR / relative_path
        if not path.exists():
            raise GIEServiceError(f"Missing required GIE prompt file: {path}", recoverable=True)
        return path.read_text(encoding="utf-8").strip()

    def _validate_suggestions(value) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("suggestions must be a list.")
        suggestions = [str(item).strip() for item in value if str(item).strip()]
        if len(suggestions) < 2:
            raise ValueError("suggestions must contain at least two items.")
        return suggestions[:4]

    normalized_goal = (goal_text or "").strip()
    if not normalized_goal:
        raise GIEServiceError("goal_text is required for GIE question generation.", recoverable=True)

    try:
        try:
            from ai.providers.router import create_routed_provider
            from ai.utils.parsers import ResponseParser
        except ModuleNotFoundError:
            from roadmap.ai.providers.router import create_routed_provider
            from roadmap.ai.utils.parsers import ResponseParser

        classifier_prompt = _load_prompt("classifier.txt")
        provider = create_routed_provider(
            task_name="gie_question_generation",
            temperature=0.0,
            max_tokens=300,
        )
        classification_response = provider.generate_response(
            prompt=f"Goal text:\n{normalized_goal}",
            system_prompt=classifier_prompt,
        )
        classification_payload = ResponseParser.parse_json(classification_response.content)
        if not isinstance(classification_payload, dict):
            raise ValueError("Classifier response must be a JSON object.")

        category = str(classification_payload.get("category", "")).strip().lower()
        if category not in CATEGORY_LABELS:
            raise ValueError(f"Unsupported GIE category '{category}'.")

        category_questions = _load_prompt(f"categories/{category}/questions.txt")
        category_label = str(classification_payload.get("category_label") or CATEGORY_LABELS[category]).strip()
        total_questions = classification_payload.get("total_questions", DEFAULT_TOTAL_QUESTIONS)
        if not isinstance(total_questions, int) or total_questions < 1:
            raise ValueError("total_questions must be a positive integer.")
        total_questions = min(total_questions, DEFAULT_TOTAL_QUESTIONS)

        target_slot_lines = []
        if target_slot_key:
            target_slot_lines.append(f"Target slot key: {target_slot_key}")
        if target_slot_label:
            target_slot_lines.append(f"Target slot label: {target_slot_label}")
        if target_slot_description:
            target_slot_lines.append(f"Target slot description: {target_slot_description}")
        target_slot_context = "\n".join(target_slot_lines)

        first_question_response = provider.generate_response(
            prompt=(
                "Generate the first question for this guided goal intake.\n\n"
                f"Goal text:\n{normalized_goal}\n\n"
                f"Category: {category}\n"
                f"Category label: {category_label}\n"
                "Next question number: 1\n"
                "Conversation history: []\n\n"
                f"{target_slot_context}\n\n"
                f"Category question bank:\n{category_questions}"
            ),
            system_prompt=_load_prompt("next_question.txt"),
        )
        first_question_payload = ResponseParser.parse_json(first_question_response.content)
        if not isinstance(first_question_payload, dict):
            raise ValueError("First-question response must be a JSON object.")

        question = str(first_question_payload.get("question", "")).strip()
        if not question:
            raise ValueError("question is required.")

        return {
            "category": category,
            "category_label": category_label,
            "total_questions": total_questions,
            "current_question_number": 1,
            "question": question,
            "suggestions": _validate_suggestions(first_question_payload.get("suggestions", [])),
        }
    except GIEServiceError:
        raise
    except Exception as exc:
        raise GIEServiceError(f"Failed to classify and generate the first GIE question: {exc}", recoverable=True) from exc


def generate_next_question(
    goal_text: str,
    category: str,
    conversation_history: list[dict],
    *,
    target_slot_key: str | None = None,
    target_slot_label: str | None = None,
    target_slot_description: str | None = None,
):
    def _load_prompt(relative_path: str) -> str:
        path = PROMPTS_DIR / relative_path
        if not path.exists():
            raise GIEServiceError(f"Missing required GIE prompt file: {path}", recoverable=True)
        return path.read_text(encoding="utf-8").strip()

    def _validate_history(value: list[dict]) -> list[dict]:
        if not isinstance(value, list) or not value:
            raise ValueError("conversation_history must be a non-empty list.")
        normalized_history: list[dict] = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("Each conversation history item must be an object.")
            question = str(item.get("question", "")).strip()
            answer = str(item.get("answer", "")).strip()
            if not question or not answer:
                raise ValueError("Each conversation history item must include question and answer.")
            normalized_history.append({"question": question, "answer": answer})
        return normalized_history

    def _validate_suggestions(value) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("suggestions must be a list.")
        suggestions = [str(item).strip() for item in value if str(item).strip()]
        if len(suggestions) < 2:
            raise ValueError("suggestions must contain at least two items.")
        return suggestions[:4]

    normalized_goal = (goal_text or "").strip()
    normalized_category = (category or "").strip().lower()
    if not normalized_goal:
        raise GIEServiceError("goal_text is required for GIE question generation.", recoverable=True)
    if normalized_category not in CATEGORY_LABELS:
        raise GIEServiceError(f"Unsupported GIE category '{category}'.", recoverable=True)

    try:
        try:
            from ai.providers.router import create_routed_provider
            from ai.utils.parsers import ResponseParser
        except ModuleNotFoundError:
            from roadmap.ai.providers.router import create_routed_provider
            from roadmap.ai.utils.parsers import ResponseParser

        history = _validate_history(conversation_history)
        next_question_number = len(history) + 1
        provider = create_routed_provider(
            task_name="gie_question_generation",
            temperature=0.2,
            max_tokens=300,
        )
        target_slot_lines = []
        if target_slot_key:
            target_slot_lines.append(f"Target slot key: {target_slot_key}")
        if target_slot_label:
            target_slot_lines.append(f"Target slot label: {target_slot_label}")
        if target_slot_description:
            target_slot_lines.append(f"Target slot description: {target_slot_description}")
        target_slot_context = "\n".join(target_slot_lines)

        response = provider.generate_response(
            prompt=(
                "Generate the next question for this guided goal intake.\n\n"
                f"Goal text:\n{normalized_goal}\n\n"
                f"Category: {normalized_category}\n"
                f"Category label: {CATEGORY_LABELS[normalized_category]}\n"
                f"Next question number: {next_question_number}\n"
                "Conversation history JSON:\n"
                f"{json.dumps(history, ensure_ascii=True, indent=2)}\n\n"
                f"{target_slot_context}\n\n"
                "Category question bank:\n"
                f"{_load_prompt(f'categories/{normalized_category}/questions.txt')}"
            ),
            system_prompt=_load_prompt("next_question.txt"),
        )
        payload = ResponseParser.parse_json(response.content)
        if not isinstance(payload, dict):
            raise ValueError("Next-question response must be a JSON object.")

        question = str(payload.get("question", "")).strip()
        if not question:
            raise ValueError("question is required.")

        current_question_number = payload.get("current_question_number", next_question_number)
        if not isinstance(current_question_number, int) or current_question_number != next_question_number:
            raise ValueError("current_question_number must match the requested next question number.")

        return {
            "current_question_number": current_question_number,
            "question": question,
            "suggestions": _validate_suggestions(payload.get("suggestions", [])),
        }
    except GIEServiceError:
        raise
    except Exception as exc:
        raise GIEServiceError(f"Failed to generate the next GIE question: {exc}", recoverable=True) from exc


def run_standalone_test():
    demo_goal = "I want to reduce my anxiety and sleep better over the next three months."
    try:
        print("Running classify_and_generate_first_question...")
        first_result = classify_and_generate_first_question(demo_goal)
        print(json.dumps(first_result, indent=2))

        print("\nRunning generate_next_question...")
        next_result = generate_next_question(
            goal_text=demo_goal,
            category=first_result["category"],
            conversation_history=[
                {
                    "question": first_result["question"],
                    "answer": "My stress is highest at night and my sleep is inconsistent.",
                }
            ],
        )
        print(json.dumps(next_result, indent=2))
    except GIEServiceError as exc:
        print(json.dumps({"error": str(exc), "recoverable": exc.recoverable}, indent=2))


if __name__ == "__main__":
    run_standalone_test()
