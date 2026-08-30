#requires -Version 5.1
<#
.SYNOPSIS
    pipeline/pipeline_runner.ps1

    Runs the full museum pipeline locally, in the same order as the Airflow
    DAG (dags/museum_pipeline.py):

        bronze_load -> test_bronze -> build_silver_gold -> test_silver_gold

    Stops immediately if any stage fails, so a broken bronze load never gets
    built on top of in silver/gold -- same fail-fast behaviour as
    scripts/dbt_runner.py and the Airflow DAG.

.DESCRIPTION
    Each stage shells out to `uv run scripts/<script>.py` from the project
    root (this script's parent folder), streams output to the console, logs
    it to logs/<stage>_<timestamp>.log, then prints a pass/fail summary
    table across every stage that ran.

.PARAMETER SkipTests
    Skip both test stages (test_bronze, test_silver_gold).

.PARAMETER BronzeOnly
    Stop after test_bronze (bronze_load + test_bronze only).

.PARAMETER FullRefresh
    Pass --full-refresh through to incremental.py and dbt_runner.py.

.PARAMETER ProjectRoot
    Override the auto-detected project root. By default this script assumes
    it lives at <project_root>/pipeline/pipeline_runner.ps1 and uses its own
    parent folder.

.EXAMPLE
    ./pipeline/pipeline_runner.ps1

.EXAMPLE
    ./pipeline/pipeline_runner.ps1 -SkipTests

.EXAMPLE
    ./pipeline/pipeline_runner.ps1 -FullRefresh
#>

[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$BronzeOnly,
    [switch]$FullRefresh,
    [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Project root: this script lives at <project_root>/pipeline/pipeline_runner.ps1
# ---------------------------------------------------------------------------
if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

$LogDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

Write-Host ""
Write-Host "=== museum pipeline ===" -ForegroundColor Cyan
Write-Host "project root: $ProjectRoot"
Write-Host "logs:         $LogDir"
Write-Host ""

# ---------------------------------------------------------------------------
# Stage runner
# ---------------------------------------------------------------------------
$script:Results = @()

function Invoke-Stage {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [string[]]$UvArgs
    )

    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $logPath = Join-Path $LogDir "$($Name)_$($timestamp).log"

    Write-Host ("-" * 70) -ForegroundColor DarkCyan
    Write-Host $Name -ForegroundColor Cyan
    Write-Host ("uv " + ($UvArgs -join " ")) -ForegroundColor DarkGray

    $start = Get-Date
    Push-Location -LiteralPath $ProjectRoot
    try {
        & uv @UvArgs 2>&1 | Tee-Object -FilePath $logPath
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    $duration = (Get-Date) - $start

    $success = ($exitCode -eq 0)
    if ($success) {
        Write-Host ("PASSED in {0:N1}s -- log: {1}" -f $duration.TotalSeconds, $logPath) -ForegroundColor Green
    }
    else {
        Write-Host ("FAILED (exit $exitCode) in {0:N1}s -- log: {1}" -f $duration.TotalSeconds, $logPath) -ForegroundColor Red
    }
    Write-Host ""

    $script:Results += [PSCustomObject]@{
        Stage    = $Name
        Success  = $success
        Duration = "{0:N1}s" -f $duration.TotalSeconds
        Log      = $logPath
    }

    return $success
}

function Write-Summary {
    Write-Host ""
    Write-Host "=== pipeline summary ===" -ForegroundColor Cyan
    foreach ($r in $script:Results) {
        $color = if ($r.Success) { "Green" } else { "Red" }
        $status = if ($r.Success) { "PASSED" } else { "FAILED" }
        Write-Host ("{0,-20} {1,-8} {2,-8} {3}" -f $r.Stage, $status, $r.Duration, $r.Log) -ForegroundColor $color
    }
    Write-Host ""
}

# ---------------------------------------------------------------------------
# Stage definitions, in pipeline order -- same stages/order as the DAG
# ---------------------------------------------------------------------------
$stages = [ordered]@{}

$bronzeLoadArgs = @("run", "scripts/incremental.py")
if ($FullRefresh) { $bronzeLoadArgs += "--full-refresh" }
$stages["bronze_load"] = $bronzeLoadArgs

if (-not $SkipTests) {
    $stages["test_bronze"] = @("run", "scripts/run_sql_tests.py", "--layer", "bronze")
}

if (-not $BronzeOnly) {
    $buildArgs = @("run", "scripts/dbt_runner.py", "--skip-tests")
    if ($FullRefresh) { $buildArgs += "--full-refresh" }
    $stages["build_silver_gold"] = $buildArgs

    if (-not $SkipTests) {
        $stages["test_silver_gold"] = @("run", "scripts/run_sql_tests.py", "--layer", "silver", "--layer", "gold")
    }
}

# ---------------------------------------------------------------------------
# Run stages in order, stop on first failure
# ---------------------------------------------------------------------------
$allPassed = $true
foreach ($stageName in $stages.Keys) {
    $ok = Invoke-Stage -Name $stageName -UvArgs $stages[$stageName]
    if (-not $ok) {
        $allPassed = $false
        Write-Host "Stopping pipeline: $stageName failed." -ForegroundColor Red
        break
    }
}

Write-Summary

if (-not $allPassed) {
    exit 1
}
exit 0