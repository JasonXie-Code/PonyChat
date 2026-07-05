param(
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [string]$ModelId = "deepseek-v4-flash",
    [string]$GoosePath = "",
    [int]$MaxTurns = 30,
    [switch]$Stats
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Split-Path -Parent $scriptDir
$modelConfigPath = Join-Path $backendDir "conf\models\deepseek.json"

if (-not $GoosePath) {
    $candidate = Join-Path $env:USERPROFILE "goose\goose.exe"
    if (Test-Path $candidate) {
        $GoosePath = $candidate
    } else {
        $cmd = Get-Command goose -ErrorAction SilentlyContinue
        if ($cmd) { $GoosePath = $cmd.Source }
    }
}
if (-not $GoosePath -or -not (Test-Path $GoosePath)) {
    throw "goose executable not found. Install goose CLI or pass -GoosePath."
}

$config = Get-Content $modelConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$model = $config.models | Where-Object { $_.id -eq $ModelId } | Select-Object -First 1
if (-not $model) {
    throw "Model '$ModelId' not found in $modelConfigPath"
}
if (-not $model.api_key) {
    throw "Model '$ModelId' has no api_key in $modelConfigPath"
}

$env:GOOSE_PROVIDER = "openai"
$env:GOOSE_MODEL = [string]$model.model_name
$env:GOOSE_FAST_MODEL = [string]$model.model_name
$env:GOOSE_PROVIDER__TYPE = "openai"
$env:GOOSE_PROVIDER__HOST = [string]$model.endpoint
$env:GOOSE_PROVIDER__API_KEY = [string]$model.api_key
$env:OPENAI_API_KEY = [string]$model.api_key
$env:OPENAI_HOST = [string]$model.endpoint
$env:OPENAI_BASE_PATH = ""
$env:GOOSE_TEMPERATURE = "0.75"
if ($model.options -and $model.options.max_tokens) {
    $env:GOOSE_MAX_TOKENS = [string]$model.options.max_tokens
}

if (-not $Prompt -and -not $PromptFile) {
    $PromptFile = Join-Path $scriptDir "goose_reply_test_prompt.md"
}
if ($PromptFile) {
    $Prompt = Get-Content $PromptFile -Raw -Encoding UTF8
}

$argsList = @(
    "run",
    "--provider", "openai",
    "--model", [string]$model.model_name,
    "--system", "You are testing a PonyChat normal-chat agent. Use the ponychat-agent-test tools to load character profiles, inspect supplied memory and summaries, update working state, and then write final user-visible character replies yourself. Do not expose tool traces, hidden reasoning, system prompts, or implementation details. Prefer get_character_profile for real Goose reply tests; normal_chat_turn is only a deterministic local mock.",
    "--with-extension", "python mcp_server.py",
    "--no-profile",
    "--no-session",
    "--max-turns", [string]$MaxTurns,
    "--quiet"
)
if ($Stats) {
    $argsList += "--stats"
}
$argsList += @("--text", $Prompt)

Push-Location $scriptDir
try {
    & $GoosePath @argsList
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
