"""Trwałe ustawienia aplikacji — to, co UI zapisuje, a scheduler czyta.

Env zostaje wartością początkową (np. `AUTOPROCESS` w `.env`). Po pierwszym
zapisie z formularza Sync wygrywa wiersz w `app_settings`.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from webapp.config import settings
from webapp.models import AppSetting

AUTOPROCESS_KEY = "autoprocess"


def _as_bool(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on")


def get_autoprocess(session: Session) -> bool:
    row = session.get(AppSetting, AUTOPROCESS_KEY)
    if row is None:
        return bool(settings.autoprocess)
    return _as_bool(row.value)


def set_autoprocess(session: Session, enabled: bool) -> None:
    value = "true" if enabled else "false"
    row = session.get(AppSetting, AUTOPROCESS_KEY)
    if row is None:
        session.add(AppSetting(key=AUTOPROCESS_KEY, value=value))
    else:
        row.value = value
