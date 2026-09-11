param(
    [ValidateSet("SAFE", "CONFIRM_TEST")]
    [string]$Mode = "SAFE"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

function Invoke-CondaPython {
    param(
        [Parameter(Mandatory = $true)][string]$Environment,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    & conda run --no-capture-output -n $Environment python -u @Arguments | Out-Host
    $code = $LASTEXITCODE
    return $code
}

if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    throw "Conda is not available on PATH. Open Anaconda Prompt and rerun PHASE2_RUN_AND_FREEZE.bat."
}

Write-Host "=== AviMaint thesis Phase 2: missing evidence completion ==="
Write-Host "Mode: $Mode"
Write-Host "Policy: inference/evaluation only; no training or retuning"

$normalizationArgs = @("scripts\phase2\freeze_normalization_test.py", "--repo-root", $RepoRoot, "--check")
$normalizationStatus = Invoke-CondaPython -Environment "avimaint-normalization" -Arguments $normalizationArgs

if ($normalizationStatus -eq 10) {
    if ($Mode -ne "CONFIRM_TEST") {
        Write-Host ""
        Write-Host "The sealed 741-record normalization TEST outputs are absent."
        Write-Host "SAFE mode has not opened the test. Review the frozen validation selection, then run:"
        Write-Host "  PHASE2_RUN_AND_FREEZE.bat CONFIRM_TEST"
        exit 10
    }
    Write-Host "Running the repository's existing gated normalization TEST evaluator once..."
    & cmd /d /c "call scripts\normalization\06_run_final_test_once.bat CONFIRM_TEST"
    if ($LASTEXITCODE -ne 0) {
        throw "The existing normalization final-test runner failed with exit code $LASTEXITCODE."
    }
} elseif ($normalizationStatus -ne 0) {
    throw "Normalization evidence validation failed with exit code $normalizationStatus."
} else {
    Write-Host "Existing 741-record normalization TEST outputs found; reusing them."
}

$freezeNormalization = Invoke-CondaPython -Environment "avimaint-normalization" -Arguments @(
    "scripts\phase2\freeze_normalization_test.py", "--repo-root", $RepoRoot, "--freeze"
)
if ($freezeNormalization -ne 0) {
    throw "Normalization evidence freeze failed with exit code $freezeNormalization."
}

$robustness = Invoke-CondaPython -Environment "avimaint-retrieval" -Arguments @(
    "scripts\phase2\run_selective_robustness.py", "--repo-root", $RepoRoot
)
if ($robustness -ne 0) {
    throw "Selective robustness evaluation failed with exit code $robustness."
}

$finalize = Invoke-CondaPython -Environment "avimaint-normalization" -Arguments @(
    "scripts\phase2\finalize_phase2.py", "--repo-root", $RepoRoot
)
if ($finalize -ne 0) {
    throw "Phase 2 final verification failed with exit code $finalize."
}

Write-Host ""
Write-Host "PHASE 2 COMPLETE"
Write-Host "Evidence manifest: outputs\frozen\phase2_evidence_completion_v1\PHASE2_COMPLETION_MANIFEST.json"
Write-Host "Thesis report:     outputs\frozen\phase2_evidence_completion_v1\PHASE2_COMPLETION_REPORT.md"
exit 0
