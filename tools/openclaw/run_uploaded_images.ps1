param(
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][int]$FolderId,
    [ValidateSet("upload", "line-auto")]
    [string]$TriggerSource = "upload"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$RpaPython = if ($env:RPA_PYTHON) { $env:RPA_PYTHON } else { "C:\Users\user\anaconda3\python.exe" }
$DefaultPipelinePython = "C:\Users\user\anaconda3\envs\asr\python.exe"
if (-not (Test-Path $DefaultPipelinePython)) {
    $DefaultPipelinePython = "C:\Users\user\anaconda3\python.exe"
}
$PipelinePython = if ($env:PIPELINE_PYTHON) { $env:PIPELINE_PYTHON } else { $DefaultPipelinePython }
$LogDir = Join-Path $ProjectRoot "logs\openclaw"
$LockPath = Join-Path $LogDir "line-rpa-scheduled.lock"
$JobStatusPath = Join-Path $LogDir "latest_job.json"
$RapidOcrModelDir = Join-Path $ProjectRoot ".cache\rapidocr-models"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $Utf8
[Console]::OutputEncoding = $Utf8
$OutputEncoding = $Utf8
try {
    chcp 65001 | Out-Null
} catch {}

$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogPath = Join-Path $LogDir "uploaded-images-$RunStamp.log"
$JobId = "$RunStamp-$TriggerSource-$Target"
$LogRelPath = "logs/openclaw/uploaded-images-$RunStamp.log"
$LockRelPath = "logs/openclaw/line-rpa-scheduled.lock"
$Script:JobState = $null
$Script:JobFinished = $false

function Get-IsoUtcNow {
    return (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}

function Update-FolderCatalog {
    param(
        [string]$Status,
        [string]$CurrentStep,
        [string[]]$Steps = @()
    )
    $args = @("-X", "utf8", ".\tools\openclaw\upload_catalog.py", "update-folder", "--id", "$FolderId")
    if ($Status) { $args += @("--status", $Status) }
    if ($CurrentStep) { $args += @("--current-step", $CurrentStep) }
    $args += @("--job-id", $JobId)
    foreach ($step in $Steps) {
        $args += @("--step", $step)
    }
    & $RpaPython $args | Out-Null
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
    if ($null -eq $Script:JobState) { return }
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
        target_id = $Target
        folder_id = $FolderId
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
            upload = New-StepState
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
    if ($null -eq $step) { return }
    $step["status"] = $Status
    if ($Status -eq "running" -and $null -eq $step["started_at"]) {
        $step["started_at"] = Get-IsoUtcNow
    }
    if ($Status -in @("success", "failed", "skipped")) {
        $step["finished_at"] = Get-IsoUtcNow
    }
    if ($null -ne $ExitCode) { $step["exit_code"] = [int]$ExitCode }
    if ($null -ne $ErrorMessage) { $step["error"] = [string]$ErrorMessage }
    Save-JobStatus
    Update-FolderCatalog -Status "running" -CurrentStep $Name -Steps @("$Name=$Status")
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
    $finalStep = if ($Status -eq "success") { "done" } else { "failed" }
    Update-FolderCatalog -Status $Status -CurrentStep $finalStep
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
        Write-Log "Another image processing run appears active. Lock: $LockPath"
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
    $env:RAPIDOCR_MODEL_DIR = $RapidOcrModelDir
    foreach ($name in @("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "GIT_HTTP_PROXY", "GIT_HTTPS_PROXY")) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }

    Set-JobStep -Name "upload" -Status "success" -ExitCode 0

    [int]$ocrExit = Invoke-LoggedJobStep -StepName "ocr" -DisplayName "Uploaded image OCR sync" -Command {
        & $RpaPython "-X" "utf8" ".\tools\pipeline\process_downloads.py" `
            --python $PipelinePython `
            --target $Target `
            --assume-travel `
            --skip-branding `
            --skip-ocr-enrich `
            --skip-index `
            --json
    }

    [int]$composeExit = 0
    [int]$indexExit = 0
    if ($ocrExit -eq 0) {
        $composeExit = Invoke-LoggedJobStep -StepName "compose" -DisplayName "Uploaded image compose sync" -Command {
            & $RpaPython "-X" "utf8" ".\tools\pipeline\process_downloads.py" `
                --python $PipelinePython `
                --target $Target `
                --skip-ocr `
                --skip-ocr-enrich `
                --skip-index `
                --json
        }
    } else {
        Set-JobStep -Name "compose" -Status "skipped" -ErrorMessage "Skipped because OCR sync failed."
    }

    if ($ocrExit -eq 0 -and $composeExit -eq 0) {
        $indexExit = Invoke-LoggedJobStep -StepName "index" -DisplayName "Uploaded image index sync" -Command {
            & $RpaPython "-X" "utf8" ".\tools\pipeline\process_downloads.py" `
                --python $PipelinePython `
                --target $Target `
                --skip-ocr `
                --skip-branding `
                --json
        }
    } else {
        Set-JobStep -Name "index" -Status "skipped" -ErrorMessage "Skipped because an earlier sync step failed."
    }

    if ($ocrExit -ne 0) {
        Complete-JobStatus -Status "failed" -ReturnCode $ocrExit -ErrorMessage "Uploaded image OCR sync exited with code $ocrExit"
        exit $ocrExit
    }
    if ($composeExit -ne 0) {
        Complete-JobStatus -Status "failed" -ReturnCode $composeExit -ErrorMessage "Uploaded image compose sync exited with code $composeExit"
        exit $composeExit
    }
    if ($indexExit -ne 0) {
        Complete-JobStatus -Status "failed" -ReturnCode $indexExit -ErrorMessage "Uploaded image index sync exited with code $indexExit"
        exit $indexExit
    }
    Complete-JobStatus -Status "success" -ReturnCode 0
    exit 0
}
catch {
    $message = $_.Exception.Message
    Write-Log "Uploaded image run failed: $message"
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
}
