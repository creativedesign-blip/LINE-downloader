param(
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $ProjectRoot

$DefaultPython = "C:\Users\user\anaconda3\python.exe"
if (-not (Test-Path $DefaultPython)) {
    $DefaultPython = "python"
}
$ReportPython = if ($Python) { $Python } elseif ($env:RPA_PYTHON) { $env:RPA_PYTHON } else { $DefaultPython }

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

& $ReportPython "-X" "utf8" "-m" "tools.openclaw.learning_candidates" "report"
exit $LASTEXITCODE
