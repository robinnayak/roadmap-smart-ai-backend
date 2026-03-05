#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="python"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
fi

echo "Using Python interpreter: ${PYTHON_BIN}"

export OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-gpt-oss:120b-cloud}"
export HIERARCHY_MODEL="${HIERARCHY_MODEL:-$OLLAMA_MODEL}"
export JOURNEYBOOK_MODEL="${JOURNEYBOOK_MODEL:-$OLLAMA_MODEL}"

echo "AI model defaults: OLLAMA_MODEL=${OLLAMA_MODEL}, HIERARCHY_MODEL=${HIERARCHY_MODEL}, JOURNEYBOOK_MODEL=${JOURNEYBOOK_MODEL}"
"${PYTHON_BIN}" -m pip install -r "./roadmap/requirements.txt"
"${PYTHON_BIN}" -c "import reportlab,sys; print('reportlab', reportlab.__version__, 'from', sys.executable)"
"${PYTHON_BIN}" "./roadmap/manage.py" runserver
