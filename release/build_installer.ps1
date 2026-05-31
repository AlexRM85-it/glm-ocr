# Compila l'installer Inno Setup per la versione corrente.
# Richiede Inno Setup installato (iscc.exe nel PATH o nel percorso standard).

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$VersionFile = Join-Path $RepoRoot 'app\VERSION'
$DistDir = Join-Path $RepoRoot 'dist'
$IssFile = Join-Path $PSScriptRoot 'setup.iss'

if (-not (Test-Path $VersionFile)) {
    throw "VERSION file mancante: $VersionFile"
}
$Version = (Get-Content $VersionFile -Raw).Trim()
Write-Host "[build_installer] Versione: $Version" -ForegroundColor Cyan

# Localizza iscc.exe
$iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\iscc.exe",
        "$env:ProgramFiles\Inno Setup 6\iscc.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\iscc.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 5\iscc.exe",
        "$env:ProgramFiles\Inno Setup 5\iscc.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 5\iscc.exe"
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) { $iscc = @{ Source = $p }; break }
    }
}
if (-not $iscc) {
    Write-Host ""
    Write-Host "ERRORE: Inno Setup non trovato." -ForegroundColor Red
    Write-Host "Scarica e installa da: https://jrsoftware.org/isdl.php" -ForegroundColor Yellow
    Write-Host "Poi rilancia questo script." -ForegroundColor Yellow
    exit 1
}
Write-Host "[build_installer] ISCC: $($iscc.Source)" -ForegroundColor DarkGray

if (-not (Test-Path $DistDir)) {
    New-Item -ItemType Directory -Path $DistDir -Force | Out-Null
}

# Compila
& $iscc.Source "/DAppVersion=$Version" $IssFile
if ($LASTEXITCODE -ne 0) {
    throw "iscc fallito (exit $LASTEXITCODE)"
}

$out = Join-Path $DistDir "GLM-OCR-Setup-v$Version.exe"
if (Test-Path $out) {
    Write-Host ""
    Write-Host "[OK] Installer generato:" -ForegroundColor Green
    Write-Host "     $out" -ForegroundColor Green
} else {
    Write-Host "[WARN] iscc terminato OK ma il file output non e' presente: $out" -ForegroundColor Yellow
}
