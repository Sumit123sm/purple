param(
  [string]$Source = "tests/fixtures/sample_events.jsonl",
  [string]$ApiUrl = "http://127.0.0.1:8000",
  [double]$Speed = 120.0
)

# Ensure project root is on PYTHONPATH for imports
$projectRoot = (Get-Location).Path
$env:PYTHONPATH = $projectRoot
Write-Host "PYTHONPATH set to: $env:PYTHONPATH"

python dashboard/run.py --source $Source --api-url $ApiUrl --speed $Speed
