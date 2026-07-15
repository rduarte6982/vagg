# bootstrap.ps1 — versão PowerShell do bootstrap.sh (Windows).
# Gera dev.env com hash argon2 da senha e JWT secret aleatório.
#
# Uso:
#   .\bootstrap.ps1                          # senha "admin" / admin@vagg.local
#   .\bootstrap.ps1 -Force                   # sobrescreve dev.env
#   .\bootstrap.ps1 -Password "X"            # usa senha "X"
#   .\bootstrap.ps1 -Email "a@b.c"           # usa e-mail "a@b.c"

[CmdletBinding()]
param(
  [string]$Password = 'admin',
  [string]$Email = 'admin@vagg.local',
  [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$envFile = 'dev.env'

if ((Test-Path $envFile) -and -not $Force) {
  Write-Host "OK $envFile ja existe (use -Force para sobrescrever)"
  exit 0
}

Write-Host "-> gerando $envFile"
Write-Host "  e-mail:  $Email"
Write-Host "  senha:   $Password"

# Build da imagem vagg/core:dev (uma vez) — necessária para gerar o hash argon2.
Write-Host "  build da imagem vagg/core:dev (pode demorar na primeira vez)..."
docker build -q -t 'vagg/core:dev' ..\core | Out-Null

$hash = docker run --rm 'vagg/core:dev' python -m vagg_core.scripts.hash_password $Password
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($hash)) {
  throw 'falha ao gerar argon2 hash'
}
$hash = $hash.Trim()

# JWT secret: 48 bytes aleatórios base64.
$bytes = New-Object byte[] 48
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$jwt = [Convert]::ToBase64String($bytes)

$lines = @(
  "# Gerado por bootstrap.ps1 em $((Get-Date).ToString('o'))",
  "# Nao comitar este arquivo - contem senhas hash e segredo JWT.",
  "",
  "VAGG_ADMIN_EMAIL=$Email",
  "VAGG_ADMIN_PASSWORD_HASH=$hash",
  "VAGG_JWT_SECRET=$jwt"
)
Set-Content -Path $envFile -Value $lines -Encoding ascii

Write-Host ''
Write-Host "OK $envFile pronto."
Write-Host ''
Write-Host 'Proximos passos:'
Write-Host "  docker compose --env-file $envFile up -d --build"
Write-Host '  .\seed.ps1        # popular clientes/consultores de exemplo'
Write-Host ''
Write-Host 'Acesso:'
Write-Host "  http://localhost:8080  -> Admin UI ($Email / $Password)"
Write-Host '  http://localhost:8081  -> Portal de Transparencia'
Write-Host '  http://localhost:8443/docs  -> Swagger da API'
