param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('test', 'uat')]
    [string]$Environment,
    [ValidateSet('normal', 'empty', 'dirty', 'invalid_json', 'invalid_items', 'http_401', 'http_429', 'http_500', 'timeout', 'fail_once', 'oversize')]
    [string]$ExportScenario = 'normal',
    [ValidateSet('direct', 'body', 'data')]
    [string]$Wrapper = 'direct',
    [ValidateRange(1, 65535)]
    [int]$McpPort = 5128,
    [ValidateRange(1, 65535)]
    [int]$ApiPort = 5129,
    [ValidateRange(1, 65535)]
    [int]$MockPort = 8025,
    [string]$DockerSubnet = ''
)

$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoPath
$runtimePath = Join-Path $repoPath "deploy\environments\$Environment\runtime.env"
if (-not (Test-Path -LiteralPath $runtimePath)) { throw 'Missing non-production runtime.env' }
$environmentLine = Get-Content -LiteralPath $runtimePath -Encoding UTF8 | Where-Object { $_ -match '^\s*APP_ENV\s*=' } | Select-Object -Last 1
if ($environmentLine) {
    $configuredEnvironment = ($environmentLine.Split('=', 2)[1]).Trim().Trim('"').Trim("'")
    if ($configuredEnvironment -ne $Environment) { throw 'runtime.env APP_ENV does not match selected test/uat environment' }
}
$env:APP_ENV = $Environment
$env:BJS_ENV_FILE = $runtimePath
$env:DMP_MOCK_EXPORT_SCENARIO = $ExportScenario
$env:DMP_MOCK_WRAPPER = $Wrapper
$env:DATA_MCP_PORT = [string]$McpPort
$env:REPORT_AGENT_PORT = [string]$ApiPort
$env:DMP_MOCK_PORT = [string]$MockPort
if (-not $DockerSubnet) { $DockerSubnet = if ($Environment -eq 'test') { '10.201.0.0/24' } else { '10.202.0.0/24' } }
$env:BJS_DOCKER_SUBNET = $DockerSubnet
# Distinct Compose project and workspace per environment; no production services are selected.
& docker compose --project-name "bjs-$Environment" --env-file $runtimePath -f compose.yaml -f compose.dmp-mock.yaml --profile dmp-mock up -d --build
exit $LASTEXITCODE
