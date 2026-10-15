#!/usr/bin/env bash
# One command to get the demo on screen.
#
#   ./run.sh              generate docs if needed, ingest if needed, serve
#   ./run.sh --reset      re-render documents and re-ingest from scratch
#   ./run.sh --eval       run the evaluation suite instead of serving
#   ./run.sh --port 9000  serve on another port
set -euo pipefail
cd "$(dirname "$0")"

PORT=8765
RESET=0
EVAL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --reset) RESET=1 ;;
    --eval)  EVAL=1 ;;
    --port)  PORT="$2"; shift ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '\033[35m==>\033[0m %s\n' "$1"; }

# --- preflight ---------------------------------------------------------------
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
if ! "${BUILD_CLI_BIN:-$HOME/.local/bin/build-cli}" auth token >/dev/null 2>&1; then
  echo "Not authenticated to the Roche AI Gateway." >&2
  echo "Run:  build-cli login" >&2
  exit 1
fi

# --- documents ---------------------------------------------------------------
if [ "$RESET" = 1 ] || [ ! -f docs/manifest.json ]; then
  say "rendering synthetic scanned documents"
  python3 make_demo_docs.py
fi

# --- ingestion ---------------------------------------------------------------
INGESTED=$(python3 -c 'import store; print(len(store.list_documents()))' 2>/dev/null || echo 0)
if [ "$RESET" = 1 ]; then
  say "ingesting from scratch (vision -> extract -> validate)"
  python3 pipeline.py --reset
elif [ "$INGESTED" = "0" ]; then
  say "ingesting (vision -> extract -> validate)"
  python3 pipeline.py
else
  say "$INGESTED document(s) already ingested — use --reset to redo"
fi

# --- eval or serve -----------------------------------------------------------
if [ "$EVAL" = 1 ]; then
  say "running evaluation suite"
  exec python3 eval_run.py
fi

say "serving on http://localhost:$PORT"
( sleep 1; command -v open >/dev/null && open "http://localhost:$PORT" ) &
exec python3 app.py "$PORT"
