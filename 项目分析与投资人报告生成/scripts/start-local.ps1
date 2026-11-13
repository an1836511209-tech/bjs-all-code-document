param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('mcp', 'api', 'workbook-worker', 'migrate-workbook', 'dmp-mock', 'check-dmp-mock')]
    [string]$Service,
    [ValidateSet('normal', 'empty', 'dirty', 'invalid_json', 'invalid_items', 'http_401', 'http_429', 'http_500', 'timeout', 'fail_once', 'oversize')]
    [string]$ExportScenario = 'normal',
    [ValidateSet('direct', 'body', 'data')]
    [string]$Wrapper = 'direct',
    [ValidateRange(1, 65535)]
    [int]$MockPort = 8025,
    [ValidateRange(1, 1000)]
    [int]$Iterations = 100
)

$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoPath
$pythonPath = Join-Path $repoPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Missing .venv. Install project dependencies before starting services.'
}
$env:PYTHONIOENCODING = 'utf-8'
if ($Service -eq 'dmp-mock') {
    $env:APP_ENV = 'test'
    & $pythonPath -m scripts.dmp_mock.server --port $MockPort --export-scenario $ExportScenario --wrapper $Wrapper
    exit $LASTEXITCODE
}
if ($Service -eq 'check-dmp-mock') {
    & $pythonPath -m scripts.dmp_mock.verify --iterations $Iterations
    exit $LASTEXITCODE
}
$envPath = Join-Path $repoPath 'deploy\environments\test\runtime.env'
foreach ($line in (Get-Content -LiteralPath $envPath -Encoding UTF8)) {
    $entry = $line.Trim()
    if (-not $entry -or $entry.StartsWith('#')) { continue }
    $equals = $entry.IndexOf('=')
    if ($equals -lt 1) { continue }
    $key = $entry.Substring(0, $equals).Trim()
    $value = $entry.Substring($equals + 1).Trim()
    if ($value.Length -ge 2 -and (
        ($value.StartsWith('"') -and $value.EndsWith('"')) -or
        ($value.StartsWith("'") -and $value.EndsWith("'"))
    )) { $value = $value.Substring(1, $value.Length - 2) }
    [Environment]::SetEnvironmentVariable($key, $value, 'Process')
}
$env:REPORT_AGENT_CONFIG = Join-Path $repoPath 'deploy\environments\test\report-agent.local.yaml'
$env:DATA_MCP_CONFIG = Join-Path $repoPath 'deploy\environments\test\data-mcp.yaml'
$env:DMP_MOCK_BASE_URL = "http://127.0.0.1:$MockPort"
$env:PYTHONIOENCODING = 'utf-8'

switch ($Service) {
    'mcp' {
        & $pythonPath -m data_mcp.entrypoints --transport streamable-http --host 127.0.0.1 --port 8001
    }
    'api' {
        & $pythonPath -m report_agent.entrypoints.api --host 127.0.0.1 --port 8000
    }
    'workbook-worker' {
        & $pythonPath -m report_agent.entrypoints.institution_workbook_worker
    }
    'migrate-workbook' {
        & $pythonPath -m report_agent.entrypoints.db_migrate --apply --migration apps/report_agent/migrations/003_institution_workbook.sql
    }
}
exit $LASTEXITCODE
