#!/usr/bin/env zsh
# Launcher script to start Claude Kill Switch UI and open the browser
SCRIPT_DIR="${0:A:h}"
ROOT_DIR="${SCRIPT_DIR:A:h}"
PORT=54321

# Check if already running
if lsof -Pi :${PORT} -sTCP:LISTEN -t >/dev/null ; then
  echo "UI server is already running on http://127.0.0.1:${PORT}"
else
  echo "Starting UI server in background..."
  nohup /usr/bin/python3 "${ROOT_DIR}/bin/ui_server.py" >/dev/null 2>&1 &
  sleep 0.8
fi

echo "Opening http://127.0.0.1:${PORT} in your browser..."
/usr/bin/open "http://127.0.0.1:${PORT}"
