# Genera lo zip update + manifest.json a partire da app/.
# Output in dist/, da caricare come asset di una GitHub Release.

[CmdletBinding()]
param(
    [switch]$RequirementsChanged,
    [switch]$ModelPullRequired,
    [string]$ModelTag = 'glm-ocr:latest',
    [string]$Notes = ''
)

$ErrorActionPreference = 'Stop'

$RepoRoot   = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$AppDir     = Join-Path $RepoRoot 'app'
$DistDir    = Join-Path $RepoRoot 'dist'
$Template   = Join-Path $PSScriptRoot 'manifest.template.json'

if (-not (Test-Path $AppDir))  { throw "app/ non trovato in $RepoRoot" }
if (-not (Test-Path $Template)) { throw "Template manifest non trovato: $Template" }

$Version = (Get-Content (Join-Path $AppDir 'VERSION') -Raw).Trim()
Write-Host "[build_update] Versione: $Version" -ForegroundColor Cyan

if (-not (Test-Path $DistDir)) {
    New-Item -ItemType Directory -Path $DistDir -Force | Out-Null
}

$ZipName = "glm-ocr-app-v$Version.zip"
$ZipPath = Join-Path $DistDir $ZipName

# Zippa il CONTENUTO di app/ (non la cartella stessa), escludendo __pycache__.
$tmp = Join-Path $env:TEMP "glm-ocr-app-stage-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
try {
    Get-ChildItem -Path $AppDir -Force | Where-Object {
        $_.Name -ne '__pycache__'
    } | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination $tmp -Recurse -Force
    }
    # Pulisci __pycache__ ricorsivi dal copy.
    Get-ChildItem -Path $tmp -Directory -Recurse -Filter '__pycache__' |
        Remove-Item -Recurse -Force

    if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
    Compress-Archive -Path (Join-Path $tmp '*') -DestinationPath $ZipPath -CompressionLevel Optimal
} finally {
    Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

$sha = (Get-FileHash -Path $ZipPath -Algorithm SHA256).Hash

# Genera manifest dal template.
$manifestPath = Join-Path $DistDir 'manifest.json'
$manifest = Get-Content $Template -Raw |
    ForEach-Object { $_ -replace '\$\{version\}', $Version } |
    ForEach-Object { $_ -replace '\$\{requirements_changed\}', $RequirementsChanged.IsPresent.ToString().ToLower() } |
    ForEach-Object { $_ -replace '\$\{model_pull_required\}', $ModelPullRequired.IsPresent.ToString().ToLower() } |
    ForEach-Object { $_ -replace '\$\{model_tag\}', $ModelTag } |
    ForEach-Object { $_ -replace '\$\{notes\}', ($Notes -replace '"', '\"') } |
    ForEach-Object { $_ -replace '\$\{sha256\}', $sha } |
    ForEach-Object { $_ -replace '\$\{zip_name\}', $ZipName }

Set-Content -Path $manifestPath -Value $manifest -Encoding utf8

Write-Host ""
Write-Host "[OK] Update package generato:" -ForegroundColor Green
Write-Host "     $ZipPath  ($([math]::Round((Get-Item $ZipPath).Length / 1KB, 1)) KB)" -ForegroundColor Green
Write-Host "     $manifestPath" -ForegroundColor Green
Write-Host ""
Write-Host "Carica entrambi come asset della release GitHub v${Version}:" -ForegroundColor Cyan
Write-Host "  - $ZipName" -ForegroundColor White
Write-Host "  - manifest.json" -ForegroundColor White
Write-Host "(opzionale: GLM-OCR-Setup-v${Version}.exe per chi installa da zero)" -ForegroundColor DarkGray
