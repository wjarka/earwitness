#!/usr/bin/env bash
# Odpala webapp + workera razem i ubija oba na Ctrl-C.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# Worker też przeładowujemy po zmianie kodu. Bez tego uvicorn (--reload) zna
# nowy task, a worker wciąż siedzi na module sprzed edycji i zgłasza
# „No handler for ..." — kolejka wygląda na zepsutą, choć zepsuty jest tylko
# jeden proces, który nikt nie pomyślał zrestartować.
uv run watchfiles --filter python "python -m webapp.worker" webapp transcripts &
uv run uvicorn webapp.app:app --reload --port "$PORT" &

echo "→ http://localhost:${PORT}"
wait
