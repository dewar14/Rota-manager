#!/usr/bin/env bash
# Always-works static server launcher for roster outputs.
# - Ensures out/index.html and out/roster.csv exist (creates placeholders if missing)
# - Kills any previous python http.server on the chosen port
# - Serves the out/ directory as the web root so '/' loads index.html directly
# - Attempts to open the correct URL in a browser (Codespaces or local dev container)

set -euo pipefail
PORT="${PORT:-8000}"
OUT_DIR="out"

# Create output directory
mkdir -p "${OUT_DIR}"

# Minimal placeholder roster.csv if not present
if [ ! -f "${OUT_DIR}/roster.csv" ]; then
  cat > "${OUT_DIR}/roster.csv" <<'CSV'
Date,ExamplePerson
2025-01-01,LD
2025-01-02,N
2025-01-03,OFF
CSV
fi

# Minimal index.html if not present
if [ ! -f "${OUT_DIR}/index.html" ]; then
  cat > "${OUT_DIR}/index.html" <<'HTML'
<!doctype html>
<meta charset="utf-8" />
<title>Roster Output</title>
<style>
 body { font-family: system-ui, Arial, sans-serif; margin: 2rem; }
 table { border-collapse: collapse; }
 td, th { border: 1px solid #ccc; padding: 4px 8px; }
 code { background:#f5f5f5; padding:2px 4px; }
</style>
<h1>Roster Output</h1>
<p>This page is served from <code>out/</code>. If you regenerate rosters, refresh.</p>
<ul>
  <li><a href="roster.csv">Download roster.csv</a></li>
</ul>
<p>Command used: <code>python3 -m http.server PORT -d out</code></p>
HTML
fi

# Kill any existing server on this port started with http.server
if pids=$(lsof -t -i :"${PORT}" -sTCP:LISTEN 2>/dev/null); then
  echo "[serve_out] Killing existing processes on port ${PORT}: ${pids}" >&2
  # shellcheck disable=SC2086
  kill $pids || true
  sleep 0.3
fi

# Start new server in background
python3 -m http.server "${PORT}" -d "${OUT_DIR}" >/dev/null 2>&1 &
SERVER_PID=$!

sleep 0.5
if ! kill -0 "$SERVER_PID" 2>/dev/null; then
  echo "[serve_out] Failed to start server" >&2
  exit 1
fi

# Construct URL (Codespaces vs local)
if [ -n "${CODESPACE_NAME:-}" ] && [ -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]; then
  URL="https://${CODESPACE_NAME}-${PORT}.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}/"
else
  URL="http://localhost:${PORT}/"
fi

echo "[serve_out] Serving ${OUT_DIR} at: ${URL}" >&2

echo "[serve_out] To stop: kill ${SERVER_PID}" >&2

# Attempt to open a browser if possible
BROWSER_CMD="${BROWSER:-}"
if [ -n "$BROWSER_CMD" ]; then
  "$BROWSER_CMD" "$URL" || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 || true
fi

# Print tail of index for confirmation
head -n 5 "${OUT_DIR}/index.html" >&2

echo "[serve_out] Done." >&2
