param(
    [switch]$SkipLaunch,
    [switch]$RegenerateData,
    [switch]$SkipInstall,
    [switch]$NoDemoMail
)

$ErrorActionPreference = "Stop"
$triageStartedMail = $null
$triageMailWorker = $null

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
    Invoke-CheckedCommand -Executable $venvPython -CommandArgs @("scripts/setup_support_inbox.py")

    if ($RegenerateData) {
        Invoke-CheckedCommand -Executable $venvPython -CommandArgs @("scripts/generate_synthetic_data.py")
    }
    Invoke-CheckedCommand -Executable $venvPython -CommandArgs @("scripts/train_classifier.py")
    Invoke-CheckedCommand -Executable $venvPython -CommandArgs @("scripts/evaluate.py")
    Invoke-CheckedCommand -Executable $venvPython -CommandArgs @("-m", "pytest")

    if (-not $SkipLaunch) {
        if (-not $NoDemoMail) {
            $triageDemoMailEnabled = & $venvPython -c "from pathlib import Path; import tomllib; p=Path('.streamlit/secrets.toml'); c=tomllib.loads(p.read_text(encoding='utf-8')) if p.exists() else {}; print(c.get('smtp',{}).get('host') in ('127.0.0.1','localhost') and c.get('smtp',{}).get('port') == 1025)"
            if ($triageDemoMailEnabled -eq 'True' -and -not (Get-NetTCPConnection -LocalPort 1025 -State Listen -ErrorAction SilentlyContinue)) {
                $triageStartedMail = Start-Process -FilePath $venvPython -ArgumentList @('scripts/demo_mail_server.py') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
            }
        }
        $triageMailWorker = Start-Process -FilePath $venvPython -ArgumentList @('scripts/send_pending_mail.py','--watch') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
        Invoke-CheckedCommand -Executable $venvPython -CommandArgs @("-m", "streamlit", "run", "app.py", "--server.address=127.0.0.1")
    }
} finally {
    if ($triageStartedMail -and -not $triageStartedMail.HasExited) { Stop-Process -Id $triageStartedMail.Id }
    if ($triageMailWorker -and -not $triageMailWorker.HasExited) { Stop-Process -Id $triageMailWorker.Id }
    Pop-Location
}
