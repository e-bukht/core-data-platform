$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:CORE_PLATFORM_DATABASE_URL = "postgresql+psycopg://coredata_runtime:local-runtime-only@localhost:5434/coredata"
$env:CORE_PLATFORM_MIGRATION_DATABASE_URL = "postgresql+psycopg://coredata_migrator:local-migrator-only@localhost:5434/coredata"
$env:CORE_PLATFORM_OIDC_ISSUER = "http://localhost:8180/realms/core-data-platform"
$env:CORE_PLATFORM_OIDC_AUDIENCE = "core-data-api"

uv run alembic upgrade head
uv run python scripts/bootstrap_context_trust.py

docker compose -f deploy/local/compose.yaml --profile identity up -d keycloak

$tokenEndpoint = "http://localhost:8180/realms/core-data-platform/protocol/openid-connect/token"
$token = $null
for ($i = 0; $i -lt 40 -and -not $token; $i++) {
    try {
        $response = Invoke-RestMethod -Method Post -Uri $tokenEndpoint -ContentType "application/x-www-form-urlencoded" -Body @{
            grant_type = "password"
            client_id = "core-data-cli"
            client_secret = "local-cli-secret"
            username = "alice"
            password = "alice-local-only"
        }
        $token = $response.access_token
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $token) { throw "Unable to obtain Keycloak access token" }

$listener = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue

if ($listener) {
    throw "Port 8080 is already in use by PID $($listener.OwningProcess)"
}

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment Python not found: $python"
}

$process = Start-Process -FilePath $python -ArgumentList "scripts\run_api.py" -PassThru -NoNewWindow

try {
    Start-Sleep -Seconds 3
    $headers = @{
        Authorization = "Bearer $token"
        "X-Tenant-Id" = "00000000-0000-7000-8000-000000000001"
		"X-Correlation-Id" = "00000000-0000-7000-8000-000000000099"
    }
    $result = Invoke-RestMethod -Uri "http://127.0.0.1:8080/platform/context" -Headers $headers
    $result | ConvertTo-Json -Depth 4
} finally {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
}
