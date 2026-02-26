$ErrorActionPreference = "Stop"

$python = "python"
if (Test-Path ".\.venv\Scripts\python.exe") {
  $python = ".\.venv\Scripts\python.exe"
}

Write-Host "Using Python interpreter: $python"
& $python -m pip install -r ".\roadmap\requirements.txt"
& $python -c "import reportlab,sys; print('reportlab', reportlab.__version__, 'from', sys.executable)"
& $python ".\roadmap\manage.py" runserver
