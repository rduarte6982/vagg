# seed.ps1 — versao PowerShell do seed.sh.
# Popula o vagg-core de teste com 3 clientes, 3 consultores e politicas
# minimas para demonstrar a Admin UI.

[CmdletBinding()]
param(
  [string]$ApiBase = 'http://localhost:8443/api/v1',
  [string]$Email,
  [string]$Password = 'admin'
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path 'dev.env')) {
  throw 'dev.env nao encontrado. rode .\bootstrap.ps1 primeiro.'
}

# Carrega VAGG_ADMIN_EMAIL do dev.env caso -Email nao tenha sido passado
if (-not $Email) {
  $line = (Get-Content dev.env | Where-Object { $_ -match '^VAGG_ADMIN_EMAIL=' } | Select-Object -First 1)
  if ($line) { $Email = ($line -split '=', 2)[1].Trim() }
  if (-not $Email) { $Email = 'admin@vagg.local' }
}

Write-Host "-> aguardando vagg-core em $ApiBase"
for ($i = 0; $i -lt 60; $i++) {
  try {
    Invoke-RestMethod -Method Get -Uri "$ApiBase/system/health" -TimeoutSec 2 | Out-Null
    break
  } catch {
    Start-Sleep -Seconds 1
  }
}

Write-Host "-> autenticando como $Email"
$body = "username=$([uri]::EscapeDataString($Email))&password=$([uri]::EscapeDataString($Password))"
$resp = Invoke-RestMethod -Method Post -Uri "$ApiBase/auth/login" `
  -ContentType 'application/x-www-form-urlencoded' -Body $body
$token = $resp.access_token
if (-not $token) { throw 'login falhou' }
$headers = @{ Authorization = "Bearer $token" }

function Send-Json($method, $path, $obj) {
  $json = $obj | ConvertTo-Json -Compress -Depth 5
  try {
    Invoke-RestMethod -Method $method -Uri "$ApiBase$path" -Headers $headers `
      -ContentType 'application/json' -Body $json
  } catch {
    Write-Host "   ! $path -> $($_.Exception.Message)"
  }
}

Write-Host '-> criando clientes (idempotente)'
Send-Json POST '/clients' @{
  id = 'petroleo'; name = 'Petroleo SA'; vpn_type = 'openvpn'
  virtual_cidr = '10.200.10.0/24'; real_cidr = '172.16.0.0/24'
  dns_server = '172.16.0.10'; nat_mappings = @()
} | Out-Null
Send-Json POST '/clients' @{
  id = 'lojas-ur'; name = 'Lojas Urano'; vpn_type = 'openconnect'
  virtual_cidr = '10.200.20.0/24'; real_cidr = '10.10.0.0/16'
  dns_server = '10.10.0.5'; nat_mappings = @()
} | Out-Null
Send-Json POST '/clients' @{
  id = 'banco'; name = 'Banco Azul'; vpn_type = 'openfortivpn'
  virtual_cidr = '10.200.30.0/24'; real_cidr = '192.168.50.0/24'
  nat_mappings = @()
} | Out-Null

Write-Host '-> criando consultores'
Send-Json POST '/consultants' @{
  email = 'paulo.silva@consultoria.com'; name = 'Paulo Silva'
  role = 'operator'; static_pool_ip = '10.8.0.5'
} | Out-Null
Send-Json POST '/consultants' @{
  email = 'beatriz.lima@consultoria.com'; name = 'Beatriz Lima'; role = 'viewer'
} | Out-Null
Send-Json POST '/consultants' @{
  email = 'andre.romero@consultoria.com'; name = 'Andre Romero'; role = 'admin'
} | Out-Null

$consultants = Invoke-RestMethod -Method Get -Uri "$ApiBase/consultants" -Headers $headers
$paulo = $consultants | Where-Object { $_.email -eq 'paulo.silva@consultoria.com' } | Select-Object -First 1
$beatriz = $consultants | Where-Object { $_.email -eq 'beatriz.lima@consultoria.com' } | Select-Object -First 1

Write-Host '-> criando politicas'
if ($paulo) {
  Send-Json POST '/policies' @{
    consultant_id = $paulo.id; client_id = 'petroleo'; scope_kind = 'full'
  } | Out-Null
  Send-Json POST '/policies' @{
    consultant_id = $paulo.id; client_id = 'lojas-ur'; scope_kind = 'subnet'
    scope_value = '10.10.5.0/24'
  } | Out-Null
}
if ($beatriz) {
  Send-Json POST '/policies' @{
    consultant_id = $beatriz.id; client_id = 'banco'; scope_kind = 'host'
    scope_value = '192.168.50.10'
  } | Out-Null
}

Write-Host ''
Write-Host 'OK pronto.'
Write-Host '  http://localhost:8080  -> Admin UI'
Write-Host '  http://localhost:8081  -> Portal'
Write-Host '  http://localhost:8443/docs'
