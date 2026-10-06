param(
    [switch]$SkipLaunch,
    [switch]$RegenerateData,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

function Invoke-CheckedCommand {
    param([string]$Executable, [string[]]$CommandArgs)
    & $Executable @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit $LASTEXITCODE): $Executable $($CommandArgs -join ' ')"
    }
}

Push-Location -LiteralPath $PSScriptRoot
try {
    $env:PYTHONUTF8 = "1"
    $venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Invoke-CheckedCommand -Executable "python" -CommandArgs @("-m", "venv", ".venv")
    }

    if (-not $SkipInstall) {
        Invoke-CheckedCommand -Executable $venvPython -CommandArgs @("-m", "pip", "install", "-r", "requirements-lock.txt")
    }
    Invoke-CheckedCommand -Executable $venvPython -CommandArgs @("-m", "pip", "check")

    if ($RegenerateData) {
        Invoke-CheckedCommand -Executable $venvPython -CommandArgs @("scripts/generate_synthetic_data.py")
    }
    Invoke-CheckedCommand -Executable $venvPython -CommandArgs @("scripts/train_classifier.py")
    Invoke-CheckedCommand -Executable $venvPython -CommandArgs @("scripts/evaluate.py")
    Invoke-CheckedCommand -Executable $venvPython -CommandArgs @("-m", "pytest")

    if (-not $SkipLaunch) {
        Invoke-CheckedCommand -Executable $venvPython -CommandArgs @("-m", "streamlit", "run", "app.py", "--server.address=127.0.0.1")
    }
} finally {
    Pop-Location
}
