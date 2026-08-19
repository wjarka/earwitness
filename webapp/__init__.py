"""Webapp do transkrypcji spotkań z Recall.ai.

Uruchomienie (dwa procesy):
    uv run uvicorn webapp.app:app --reload
    uv run python -m webapp.worker
"""

__all__ = ["config", "models", "db", "jobs", "tasks"]
