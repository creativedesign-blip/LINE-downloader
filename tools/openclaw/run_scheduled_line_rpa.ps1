param(
    [ValidateSet("scheduled", "manual", "test")]
    [string]$TriggerSource = "scheduled"
)

$ErrorActionPreference = "Stop"

# Resolve project root from this script's location so the .ps1 isn't
# pinned to a single user account. RPA / pipeline python interpreters
# can be overridden per-machine via env vars (RPA_PYTHON,
# PIPELINE_PYTHON); defaults below match the original Anaconda layout.
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$RpaPython = if ($env:RPA_PYTHON) { $env:RPA_PYTHON } else { "C:\Users\user\anaconda3\python.exe" }
$PipelinePython = if ($env:PIPELINE_PYTHON) { $env:PIPELINE_PYTHON } else { "C:\Users\user\anaconda3\envs\paddleocr\python.exe" }
$ConfigPath = Join-Path $ProjectRoot "line-rpa\config.json"
$LogDir = Join-Path $ProjectRoot "logs\openclaw"
$LockPath = Join-Path $LogDir "line-rpa-scheduled.lock"
$JobStatusPath = Join-Path $LogDir "latest_job.json"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $Utf8
[Console]::OutputEncoding = $Utf8
$OutputEncoding = $Utf8
try {
    chcp 65001 | Out-Null
} catch {
    # chcp is not available in every non-interactive host; the .NET encoding
    # settings above are the important part for scheduled runs.
}

$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogPath = Join-Path $LogDir "line-rpa-scheduled-$RunStamp.log"
$JobId = "$RunStamp-$TriggerSource"
$LogRelPath = "logs/openclaw/line-rpa-scheduled-$RunStamp.log"
$LockRelPath = "logs/openclaw/line-rpa-scheduled.lock"
$Script:JobState = $null
$Script:JobFinished = $false

function Get-IsoUtcNow {
    return (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}

function New-StepState {
    return [ordered]@{
        status = "pending"
        started_at = $null
        finished_at = $null
        exit_code = $null
        error = $null
    }
}

function Save-JobStatus {
    if ($null -eq $Script:JobState) {
        return
    }
    $tmp = "$JobStatusPath.tmp"
    $json = $Script:JobState | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText($tmp, $json, $Utf8)
    try {
        if ([System.IO.File]::Exists($JobStatusPath)) {
            [System.IO.File]::Replace($tmp, $JobStatusPath, $null)
        } else {
            [System.IO.File]::Move($tmp, $JobStatusPath)
        }
    } catch {
        Move-Item -LiteralPath $tmp -Destination $JobStatusPath -Force
    }
}

function Initialize-JobStatus {
    $Script:JobState = [ordered]@{
        job_id = $JobId
        trigger_source = $TriggerSource
        status = "running"
        running = $true
        pid = $PID
        started_at = Get-IsoUtcNow
        finished_at = $null
        returncode = $null
        last_error = $null
        log_path = $LogRelPath
        lock_path = $LockRelPath
        steps = [ordered]@{
            rpa = New-StepState
            ocr = New-StepState
            compose = New-StepState
            index = New-StepState
        }
    }
    Save-JobStatus
}

function Set-JobStep {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Status,
        [object]$ExitCode = $null,
        [object]$ErrorMessage = $null
    )
    $step = $Script:JobState["steps"][$Name]
    if ($null -eq $step) {
        return
    }
    $step["status"] = $Status
    if ($Status -eq "running" -and $null -eq $step["started_at"]) {
        $step["started_at"] = Get-IsoUtcNow
    }
    if ($Status -in @("success", "failed", "skipped")) {
        $step["finished_at"] = Get-IsoUtcNow
    }
    if ($null -ne $ExitCode) {
        $step["exit_code"] = [int]$ExitCode
    }
    if ($null -ne $ErrorMessage) {
        $step["error"] = [string]$ErrorMessage
    }
    Save-JobStatus
}

function Complete-JobStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [int]$ReturnCode,
        [object]$ErrorMessage = $null
    )
    $Script:JobState["status"] = $Status
    $Script:JobState["running"] = $false
    $Script:JobState["finished_at"] = Get-IsoUtcNow
    $Script:JobState["returncode"] = $ReturnCode
    if ($null -ne $ErrorMessage) {
        $Script:JobState["last_error"] = [string]$ErrorMessage
    }
    $Script:JobFinished = $true
    Save-JobStatus
}

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    [Console]::Out.WriteLine($line)
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
}

function Write-Process-OutputToLog {
    param([scriptblock]$Command)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Command 2>&1 | ForEach-Object {
            Write-Log ([string]$_)
        }
        return [int]$LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Invoke-LoggedJobStep {
    param(
        [Parameter(Mandatory = $true)][string]$StepName,
        [Parameter(Mandatory = $true)][string]$DisplayName,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    Set-JobStep -Name $StepName -Status "running"
    Write-Log "Starting $DisplayName."
    [int]$exitCode = Write-Process-OutputToLog $Command
    Write-Log "$DisplayName finished with exit code $exitCode."
    if ($exitCode -eq 0) {
        Set-JobStep -Name $StepName -Status "success" -ExitCode $exitCode
    } else {
        Set-JobStep -Name $StepName -Status "failed" -ExitCode $exitCode -ErrorMessage "$DisplayName exited with code $exitCode"
    }
    return $exitCode
}

if (Test-Path $LockPath) {
    $age = (Get-Date) - (Get-Item $LockPath).LastWriteTime
    if ($age.TotalHours -lt 6) {
        Write-Log "Another scheduled LINE RPA run appears active. Lock: $LockPath"
        exit 0
    }
    Write-Log "Removing stale lock older than 6 hours. Lock: $LockPath"
    Remove-Item -LiteralPath $LockPath -Force
}

Set-Content -LiteralPath $LockPath -Value $PID -Encoding ASCII
Initialize-JobStatus

try {
    Set-Location $ProjectRoot
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"

    # Tier A: RPA only downloads here. The OCR/compose/index steps below
    # do all pipeline work in three shared subprocesses (one OCR-engine
    # load each), avoiding the previous double-pipeline pattern where
    # --run-pipeline spawned filter+ocr_enrich per group, then steps 2-4
    # repeated the same work for all groups. Trade-off: review/ images
    # appear after the OCR step instead of after each group's RPA finishes.
    [int]$rpaExit = Invoke-LoggedJobStep -StepName "rpa" -DisplayName "LINE RPA download" -Command {
        & $RpaPython "-X" "utf8" ".\line-rpa\line_image_downloader.py" `
            --config $ConfigPath `
            --all `
            --skip-pipeline
    }

    [int]$ocrExit = Invoke-LoggedJobStep -StepName "ocr" -DisplayName "Agent OCR sync" -Command {
        & $RpaPython "-X" "utf8" ".\tools\pipeline\process_downloads.py" `
            --python $PipelinePython `
            --skip-branding `
            --skip-ocr-enrich `
            --skip-index `
            --json
    }

    [int]$composeExit = 0
    [int]$indexExit = 0
    if ($ocrExit -eq 0) {
        $composeExit = Invoke-LoggedJobStep -StepName "compose" -DisplayName "Agent compose sync" -Command {
            & $RpaPython "-X" "utf8" ".\tools\pipeline\process_downloads.py" `
                --python $PipelinePython `
                --skip-ocr `
                --skip-ocr-enrich `
                --skip-index `
                --json
        }
    } else {
        Set-JobStep -Name "compose" -Status "skipped" -ErrorMessage "Skipped because OCR sync failed."
    }

    if ($ocrExit -eq 0 -and $composeExit -eq 0) {
        $indexExit = Invoke-LoggedJobStep -StepName "index" -DisplayName "Agent index sync" -Command {
            & $RpaPython "-X" "utf8" ".\tools\pipeline\process_downloads.py" `
                --python $PipelinePython `
                --skip-ocr `
                --skip-branding `
                --json
        }
    } else {
        Set-JobStep -Name "index" -Status "skipped" -ErrorMessage "Skipped because an earlier Agent sync step failed."
    }

    if ($rpaExit -ne 0) {
        Complete-JobStatus -Status "failed" -ReturnCode $rpaExit -ErrorMessage "LINE RPA download exited with code $rpaExit"
        exit $rpaExit
    }
    if ($ocrExit -ne 0) {
        Complete-JobStatus -Status "failed" -ReturnCode $ocrExit -ErrorMessage "Agent OCR sync exited with code $ocrExit"
        exit $ocrExit
    }
    if ($composeExit -ne 0) {
        Complete-JobStatus -Status "failed" -ReturnCode $composeExit -ErrorMessage "Agent compose sync exited with code $composeExit"
        exit $composeExit
    }
    if ($indexExit -ne 0) {
        Complete-JobStatus -Status "failed" -ReturnCode $indexExit -ErrorMessage "Agent index sync exited with code $indexExit"
        exit $indexExit
    }
    Complete-JobStatus -Status "success" -ReturnCode 0
    exit 0
}
catch {
    $message = $_.Exception.Message
    Write-Log "Scheduled LINE RPA run failed: $message"
    if ($null -ne $Script:JobState -and -not $Script:JobFinished) {
        Complete-JobStatus -Status "failed" -ReturnCode 1 -ErrorMessage $message
    }
    exit 1
}
finally {
    if ($null -ne $Script:JobState -and -not $Script:JobFinished) {
        Complete-JobStatus -Status "failed" -ReturnCode 1 -ErrorMessage "Process ended before job status was finalized."
    }
    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
    Write-Log "Scheduled LINE RPA run ended."
}
