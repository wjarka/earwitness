#!/bin/sh
# Start jednego obrazu w jednym z trzech trybów (env SERVICE):
#   web    — sam uvicorn
#   worker — sam worker kolejki
#   all    — oba procesy w jednym kontenerze (jako dev.sh, bez --reload)
#
# W trybie `all` śmierć któregoś procesu kończy kontener — platforma
# (Komodo, docker, cokolwiek) restartuje całość od zera.
set -e

MODE="${SERVICE:-all}"
PORT="${PORT:-8000}"

start_web() {
    uvicorn webapp.app:app --host 0.0.0.0 --port "$PORT"
}

start_worker() {
    python -m webapp.worker
}

case "$MODE" in
    web)
        # exec → uvicorn staje się PID 1 i dostaje sygnały platformy.
        exec uvicorn webapp.app:app --host 0.0.0.0 --port "$PORT"
        ;;
    worker)
        exec python -m webapp.worker
        ;;
    all)
        start_worker &
        worker_pid=$!
        start_web &
        web_pid=$!
        trap 'kill "$worker_pid" "$web_pid" 2>/dev/null || true' TERM INT
        while kill -0 "$worker_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do
            sleep 1
        done

        # Do not report a clean container exit if either long-running process
        # died unexpectedly; the platform should restart the service.
        exit_code=1
        if ! kill -0 "$worker_pid" 2>/dev/null; then
            wait "$worker_pid" || exit_code=$?
        fi
        if ! kill -0 "$web_pid" 2>/dev/null; then
            wait "$web_pid" || exit_code=$?
        fi
        kill "$worker_pid" "$web_pid" 2>/dev/null || true
        wait "$worker_pid" 2>/dev/null || true
        wait "$web_pid" 2>/dev/null || true
        exit "$exit_code"
        ;;
    *)
        echo "nieznany SERVICE='$MODE' (oczekiwano web|worker|all)" >&2
        exit 1
        ;;
esac
