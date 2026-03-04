import os

from common.env import get_required_env


def get_ollama_model() -> str:
    return get_required_env("OLLAMA_MODEL")


def get_hierarchy_model() -> str:
    return (os.getenv("HIERARCHY_MODEL") or "").strip() or get_ollama_model()


def get_journeybook_model() -> str:
    return (os.getenv("JOURNEYBOOK_MODEL") or "").strip() or get_ollama_model()


def get_ollama_host() -> str:
    return get_required_env("OLLAMA_HOST")

