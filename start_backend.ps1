$ErrorActionPreference = "Stop"

$python = "python"
if (Test-Path ".\.venv\Scripts\python.exe") {
  $python = ".\.venv\Scripts\python.exe"
}

Write-Host "Using Python interpreter: $python"

if (-not $env:OLLAMA_HOST) {
  $env:OLLAMA_HOST = "http://localhost:11434"
}
if (-not $env:OLLAMA_MODEL) {
  $env:OLLAMA_MODEL = "gpt-oss:120b-cloud"
}
if (-not $env:HIERARCHY_MODEL) {
  $env:HIERARCHY_MODEL = $env:OLLAMA_MODEL
}
if (-not $env:JOURNEYBOOK_MODEL) {
  $env:JOURNEYBOOK_MODEL = $env:OLLAMA_MODEL
}

Write-Host "AI model defaults: OLLAMA_MODEL=$($env:OLLAMA_MODEL), HIERARCHY_MODEL=$($env:HIERARCHY_MODEL), JOURNEYBOOK_MODEL=$($env:JOURNEYBOOK_MODEL)"
& $python -m pip install -r ".\roadmap\requirements.txt"
& $python -c "import reportlab,sys; print('reportlab', reportlab.__version__, 'from', sys.executable)"
& $python ".\roadmap\manage.py" runserver
