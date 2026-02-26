#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="python"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
fi

echo "Using Python interpreter: ${PYTHON_BIN}"
"${PYTHON_BIN}" -m pip install -r "./roadmap/requirements.txt"
"${PYTHON_BIN}" -c "import reportlab,sys; print('reportlab', reportlab.__version__, 'from', sys.executable)"
"${PYTHON_BIN}" "./roadmap/manage.py" runserver
