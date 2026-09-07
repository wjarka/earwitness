#!/usr/bin/env bash
# Stop the processes THIS run started, archive their logs as evidence,
# remove the run's temporary state, then check every recorded artifact.
#
#   scripts/cleanup.sh [run-id]
#
# Never touches other runs, dev.sh instances, or anything outside
# output/verify/<run-id>. Evidence under .verification-evidence/ is kept.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
[ $# -ge 1 ] && export VERIFY_RUN_ID="$1"
# shellcheck source=env.sh
source "$HERE/env.sh"

stop() { # stop <pidfile> <expected cmdline fragment>
  local f="$1" frag="$2" pid
  [ -f "$f" ] || return 0
  pid="$(cat "$f")"
  if kill -0 "$pid" 2>/dev/null; then
    if tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q -- "$frag"; then
      # Kill the whole group: `uv run` wraps the real uvicorn/worker process.
      pkill -TERM -P "$pid" 2>/dev/null; kill -TERM "$pid" 2>/dev/null
      for _ in $(seq 1 40); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
      kill -0 "$pid" 2>/dev/null && { pkill -KILL -P "$pid" 2>/dev/null; kill -KILL "$pid" 2>/dev/null; }
      echo "stopped $frag (pid $pid)"
    else
      echo "pid $pid no longer runs $frag; not killing" >&2
    fi
  fi
}
stop "$VERIFY_STATE/web.pid" "uvicorn"
stop "$VERIFY_STATE/worker.pid" "webapp.worker"
# Anything still bound to our port belongs to this run's uv wrapper tree.
pids="$(ss -ltnpH "sport = :$VERIFY_PORT" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u)"
for p in $pids; do kill -TERM "$p" 2>/dev/null && echo "stopped leftover listener pid $p"; done

mkdir -p "$VERIFY_EVIDENCE"
for f in web.log worker.log; do
  [ -f "$VERIFY_STATE/$f" ] && cp "$VERIFY_STATE/$f" "$VERIFY_EVIDENCE/$f" && echo "$VERIFY_EVIDENCE/$f" >> "$VERIFY_EVIDENCE/manifest.txt"
done
rm -rf "$VERIFY_STATE" && echo "removed $VERIFY_STATE"

missing=0
if [ -f "$VERIFY_EVIDENCE/manifest.txt" ]; then
  while read -r path; do
    [ -n "$path" ] || continue
    [ -e "$path" ] || { echo "MISSING evidence: $path"; missing=1; }
  done < "$VERIFY_EVIDENCE/manifest.txt"
  n="$(sort -u "$VERIFY_EVIDENCE/manifest.txt" | wc -l)"
  [ "$missing" = 0 ] && echo "evidence intact: $n artifacts in $VERIFY_EVIDENCE"
else
  echo "no manifest: this run captured no evidence" >&2; missing=1
fi
exit $missing
