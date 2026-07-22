param(
    [string]$ProjectRoot = (Get-Location).Path,
    [string]$ReviewCsv = "",
    [ValidateSet("calibration", "test")]
    [string]$EvaluationSplit = "calibration",
    [string]$ModelPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path $ProjectRoot).Path

if ([string]::IsNullOrWhiteSpace($ReviewCsv)) {
    $ReviewCsv = Join-Path $ProjectRoot "reports/manual_review/semantic_independent_eval_v1_final_review_completed.csv"
}
$ReviewCsv = (Resolve-Path $ReviewCsv).Path
$GoldCsv = Join-Path $ProjectRoot "data/evaluation/semantic_gold_v1.csv"

Write-Host "Project root: $ProjectRoot"
Write-Host "Review CSV:  $ReviewCsv"
Write-Host "Split:       $EvaluationSplit"

Push-Location $ProjectRoot
try {
    python scripts/build_semantic_gold_v1.py `
        --project-root $ProjectRoot `
        --review-input $ReviewCsv `
        --output $GoldCsv
    if ($LASTEXITCODE -ne 0) { throw "Gold build failed." }

    python -m pytest tests/test_independent_eval_v1.py -q
    if ($LASTEXITCODE -ne 0) { throw "Independent-eval tests failed." }

    $modes = @("rule_only")
    if (-not [string]::IsNullOrWhiteSpace($ModelPath)) {
        $ModelPath = (Resolve-Path $ModelPath).Path
        $modes += @("semantic_only", "combined")
    }
    elseif (Test-Path (Join-Path $ProjectRoot "models/semantic_model_v2.joblib")) {
        $ModelPath = Join-Path $ProjectRoot "models/semantic_model_v2.joblib"
        $modes += @("semantic_only", "combined")
    }
    else {
        Write-Warning "Semantic model not found. Only rule_only will be evaluated."
    }

    foreach ($mode in $modes) {
        $args = @(
            "scripts/evaluate_system_v1.py",
            "--project-root", $ProjectRoot,
            "--mode", $mode,
            "--gold", $GoldCsv,
            "--evaluation-split", $EvaluationSplit
        )
        if ($mode -ne "rule_only") {
            $args += @("--model-path", $ModelPath)
        }
        python @args
        if ($LASTEXITCODE -ne 0) { throw "Evaluation failed for mode=$mode." }
    }

    Write-Host ""
    Write-Host "Evaluation finished."
    if ($EvaluationSplit -eq "calibration") {
        Write-Host "Use calibration results to tune and freeze configuration before running the test split."
    }
    else {
        Write-Host "Test results are final reporting results; do not tune against them."
    }
}
finally {
    Pop-Location
}
